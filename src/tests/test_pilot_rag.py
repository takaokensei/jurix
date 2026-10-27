from copy import deepcopy

import pytest

from src.processing.pilot_rag import retrieve_pilot_context, stream_pilot_answer
from src.tests.test_pilot_projection import KEY, base, corpus, event


def prepared(*items):
    result = corpus(*items)
    result["corpus_revision"] = "a" * 64
    for row in result["sources"]:
        _jurisdiction, kind, number, year = row["norma_key"].split("|")
        row["identity"] = {"tipo": kind, "numero": number, "ano": int(year)}
        row["aliases"] = []
    return result


def test_exact_article_uses_typed_index_and_never_falls_back_to_another_article():
    c = prepared()
    found = retrieve_pilot_context(c, "O que prevê o Art. 1º da Lei nº 20/2020?")
    assert found["norma_keys"] == [KEY]
    assert found["sources"][0]["full_text"].startswith("Art. 1º")
    missing = retrieve_pilot_context(c, "O que prevê o Art. 999 da Lei nº 20/2020?")
    assert missing["sources"] == [] and missing["pending"][0]["reason"] == "device_missing_or_ambiguous"


def test_source_identifier_is_stable_across_modes_and_revision_is_pinned():
    c = prepared(event())
    baseline = retrieve_pilot_context(c, "Art. 1º da Lei 20/2020", arm="baseline")
    graph = retrieve_pilot_context(c, "Art. 1º da Lei 20/2020", arm="grafo")
    assert baseline["sources"][0]["citation_id"] == graph["sources"][0]["citation_id"]
    assert len(graph["sources"]) > len(baseline["sources"])
    assert all(row["corpus_revision"] == c["corpus_revision"] for row in graph["sources"])
    assert all("localhost" not in row["local_pdf_url"] for row in graph["sources"])


def test_small_whole_norm_is_not_limited_by_top_k_one():
    result = retrieve_pilot_context(prepared(), "O que prevê a Lei nº 20/2020?", arm="baseline", k=1)
    assert len(result["sources"]) == 2
    assert result["coverage"]["whole_norm_requested"] is True
    assert result["coverage"]["complete"] is True


def test_context_budget_never_truncates_the_evidence_and_reports_omissions():
    c = prepared()
    s = c["sources"][0]
    s["text"] = "Art. 1º " + "Texto extenso. " * 300
    s["devices"] = [{**s["devices"][0], "end": len(s["text"])}]
    s["page_map"][0]["end"] = len(s["text"])
    result = retrieve_pilot_context(c, "Art. 1º da Lei 20/2020", context_chars=1000)
    assert result["sources"][0]["full_text"] == s["text"]
    assert result["context_sources"] == []
    assert result["coverage"]["omitted_citation_ids"]


def test_context_is_local_to_each_conversation_including_previous_article():
    c = prepared()
    a = retrieve_pilot_context(c, "E o Art. 2º?", previous_question="Art. 1º da Lei 20/2020")
    assert a["sources"][0]["dispositivo_ref"] == "Art. 2"
    b = retrieve_pilot_context(c, "E o artigo anterior?", previous_question="Art. 2º da Lei 20/2020")
    assert b["sources"][0]["dispositivo_ref"] == "Art. 1"
    independent = retrieve_pilot_context(c, "Art. 1º da LC 20/2020")
    assert independent["sources"] == []  # Ordinary law is not a complementary law.


def test_explicit_edition_does_not_silently_use_the_primary_compilation():
    c = prepared()
    c["sources"][0].update(edition_kind="compilation", edition_year=2024)
    alternate = deepcopy(c["sources"][0])
    alternate.update(source_role="supporting", edition_year=2019, pdf_sha256="b" * 64)
    c["sources"].append(alternate)
    result = retrieve_pilot_context(c, "Art. 1º da Lei 20/2020, compilação de 2019")
    assert result["sources"][0]["document_sha256"] == "b" * 64


def test_temporal_arm_projects_but_baseline_does_not_receive_that_version():
    c = prepared(event())
    baseline = retrieve_pilot_context(c, "Art. 1º da Lei 20/2020", as_of="2025-01-09", arm="baseline")
    temporal = retrieve_pilot_context(c, "Art. 1º da Lei 20/2020", as_of="2025-01-09")
    assert baseline["casefiles"][0]["as_of"] is None
    assert temporal["casefiles"][0]["as_of"] == "2025-01-09"
    assert temporal["casefiles"][0]["devices"][0]["after"] == base()["text"][:base()["devices"][2]["start"]]


class Model:
    def __init__(self, answer):
        self.answer = answer
        self.closed = False
        self.calls = []

    def stream_text(self, prompt, **options):
        self.calls.append({"prompt": prompt, **options})
        try:
            yield self.answer
        finally:
            self.closed = True


def accept(text, rows):
    return {"grounded": True, "source_only": True, "answer": text.strip(), "grounding": {"grounded": True}}


def test_sources_are_emitted_before_provider_work_and_done_preserves_rendered_text():
    model = Model("A regra anterior está no dispositivo. [[1]]")
    stream = stream_pilot_answer(prepared(), "Art. 1º da Lei 20/2020", ollama=model, validate_attempt=accept)
    assert next(stream)["event"] == "status"
    assert next(stream)["event"] == "sources"
    assert not model.calls
    events = list(stream)
    done = events[-1]
    assert done["event"] == "done"
    assert "".join(item["chunk"] for item in events if item["event"] == "chunk").strip() == done["answer"]
    assert done["pilot"]["llm_succeeded"] is True
    assert model.closed and model.calls[0]["max_tokens"] == 512


def test_provider_failure_retains_sources_and_identifies_documentary_mode():
    class FailedModel:
        def stream_text(self, *args, **kwargs):
            raise RuntimeError("must not expose provider internals")

    events = list(stream_pilot_answer(prepared(), "Art. 1º da Lei 20/2020", ollama=FailedModel()))
    done = events[-1]
    assert done["sources"] and "Modo documental" in done["answer"]
    assert done["pilot"]["llm_succeeded"] is False
    assert done["pilot"]["fallback_reason"] == "provider_unavailable"
    assert "internals" not in done["answer"]


def test_model_urls_and_false_confirmed_validity_are_not_streamed():
    c = prepared(event(day=None))
    model = Model("A redação vigente está confirmada. https://untrusted.invalid/ [[1]]")
    events = list(stream_pilot_answer(c, "Compare a redação do Art. 1º da Lei 20/2020", ollama=model, validate_attempt=accept))
    assert "untrusted.invalid" not in "".join(item.get("chunk", "") for item in events)
    assert events[-1]["pilot"]["llm_succeeded"] is False


def test_cancel_between_sources_and_generation_has_no_done():
    from src.processing.rag_answer_pipeline import GenerationCancelled

    cancelled = False
    model = Model("Texto. [[1]]")
    stream = stream_pilot_answer(prepared(), "Art. 1º da Lei 20/2020", ollama=model, should_cancel=lambda: cancelled)
    next(stream)
    assert next(stream)["event"] == "sources"
    cancelled = True
    with pytest.raises(GenerationCancelled):
        next(stream)
    assert not model.calls
