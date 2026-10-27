"""Smoke contracts for every first-party workspace surface."""

from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser, Permission
from django.db import connection
from django.template.loader import render_to_string
from django.test import Client, RequestFactory, override_settings
from django.urls import reverse

from src.apps.ingestion.document_relation_candidates import persist_document_relation_candidates
from src.apps.legislation.document_models import DocumentoNormativo, ExtracaoDocumento
from src.apps.legislation.models import (
    ChatMessage,
    ChatSession,
    Dispositivo,
    EventoAlteracao,
    Norma,
    NormaTopic,
    Topic,
)
from src.apps.legislation.workspace_views import (
    _deduplicate_search_results,
    _parse_repeal_candidates,
    _pgm_article_evidence,
    _pgm_citation_date,
    _pgm_clean_extracted_legal_quote,
    _pgm_compare_paragraph_evidence,
    _pgm_ctm_art20_candidate_timeline,
    _pgm_ctm_lc271_change_set,
    _pgm_document_pdf_url,
    _pgm_document_review_url,
    _pgm_lc55_chain_candidate,
    _pgm_lc55_original_article_context,
    _pgm_lc258_sapl_registry_evidence,
    _pgm_paragraph_evidence,
    _pgm_reference_scope,
    _pgm_replacement_article_evidence,
    _pgm_replacement_paragraph_evidence,
    _rank_history,
)
from src.apps.operations.models import CorpusRevision
from src.processing.candidate_relation_service import classify_identity_candidates
from src.processing.normative_consolidation_preview import (
    build_article_23_snapshot,
    build_article_150_snapshot,
    build_lc271_consolidation_previews,
    extract_lc271_added_articles,
    lc271_effects_summary,
)

pytestmark = pytest.mark.django_db


@override_settings(NORMATIVE_ARCHIVE_ASSISTANT_ENABLED=True)
def test_new_assistant_exposes_both_corpus_scopes_and_preserves_prefill(client):
    consolidated = client.get(
        "/assistente/",
        {"new": "1", "question": "Art. 1º da LC 258/2024"},
    )
    archive = client.get(
        "/assistente/",
        {
            "new": "1",
            "corpus": "archive-qa",
            "question": "Art. 1º da LC 258/2024",
        },
    )

    consolidated_body = consolidated.content.decode()
    archive_body = archive.content.decode()
    assert consolidated.status_code == archive.status_code == 200
    assert 'aria-label="Escolha o acervo desta nova pesquisa"' in consolidated_body
    assert 'aria-current="true">Normas consolidadas</span>' in consolidated_body
    assert (
        'href="/assistente/?new=1&amp;corpus=archive-qa'
        '&amp;question=Art.%201%C2%BA%20da%20LC%20258/2024"'
    ) in consolidated_body
    assert 'aria-current="true">Acervo documental <small>(em revisão)</small></span>' in archive_body
    assert (
        'href="/assistente/?new=1&amp;question=Art.%201%C2%BA%20da%20LC%20258/2024"'
    ) in archive_body


@override_settings(NORMATIVE_ARCHIVE_ASSISTANT_ENABLED=True)
def test_answered_conversation_keeps_its_saved_corpus_scope(client):
    user = get_user_model().objects.create_user(username="corpus-scope-test")
    archive_session = ChatSession.objects.create(user=user, title="Acervo QA")
    ChatMessage.objects.create(
        session=archive_session,
        role="assistant",
        content="Resposta candidata.",
        metadata_json={"filters": {"corpus": "archive-qa-unvalidated"}},
    )
    consolidated_session = ChatSession.objects.create(user=user, title="Normas consolidadas")
    ChatMessage.objects.create(
        session=consolidated_session,
        role="assistant",
        content="Resposta consolidada.",
        metadata_json={"filters": {"corpus": "consolidated"}},
    )
    client.force_login(user)

    archive_response = client.get(
        f"/assistente/{archive_session.slug}/?corpus=consolidated"
    )
    consolidated_response = client.get(
        f"/assistente/{consolidated_session.slug}/?corpus=archive-qa"
    )

    archive_body = archive_response.content.decode()
    consolidated_body = consolidated_response.content.decode()
    assert archive_response.status_code == consolidated_response.status_code == 200
    assert "Escopo desta conversa:" in archive_body
    assert "Acervo documental (em revisão)" in archive_body
    assert "Escolha o acervo desta nova pesquisa" not in archive_body
    assert "Escopo desta conversa:" in consolidated_body
    assert "Normas consolidadas" in consolidated_body
    assert "Acervo documental (em revisão)" not in consolidated_body
    assert "Escolha o acervo desta nova pesquisa" not in consolidated_body


def test_ctm_art20_candidate_timeline_compares_real_editions_without_asserting_vigency():
    source_specs = [
        (
            DocumentoNormativo.SourceKind.ARCHIVE,
            "ctm-2021",
            "https://www.natal.rn.gov.br/sefin/legislacao/lei/LEI3882-1989_2021.pdf",
            {
                "identity_key": "BR-RN-NATAL|lei|municipal_lo|3882|1989",
                "edition_candidate": {"kind": "official_consolidated_text", "declared_value_year": 2021},
            },
            "Art. 20 - Redação anterior extraída do PDF.\nSeção II Do Contribuinte\nArt. 21. Outro dispositivo.",
        ),
        (
            DocumentoNormativo.SourceKind.ARCHIVE,
            "ctm-2022",
            "https://www.natal.rn.gov.br/sefin/legislacao/lei/LEI3882-1989_2022.pdf",
            {
                "identity_key": "BR-RN-NATAL|lei|municipal_lo|3882|1989",
                "edition_candidate": {"kind": "official_consolidated_text", "declared_value_year": 2022},
            },
            "Art. 20 – Redação anterior extraída do PDF.\nSeção II Do Contribuinte\nArt. 21. Outro dispositivo.",
        ),
        (
            DocumentoNormativo.SourceKind.ARCHIVE,
            "ctm-2024",
            "https://www.natal.rn.gov.br/sefin/legislacao/lei/LEI3882-1989_2024.pdf",
            {
                "identity_key": "BR-RN-NATAL|lei|municipal_lo|3882|1989",
                "edition_candidate": {"kind": "official_consolidated_text", "declared_value_year": 2024},
            },
            "Art. 20 — Redação anterior extraída do PDF.\nSeção II Do Contribuinte\nArt. 21. Outro dispositivo.",
        ),
        (
            DocumentoNormativo.SourceKind.SAPL,
            "lc271-2025",
            "https://sapl.natal.rn.leg.br/media/sapl/public/normajuridica/2025/8975/lei_complementar_no_271_2025.pdf",
            {
                "identity_key": "BR-RN-NATAL|lei_complementar|municipal_lc|271|2025",
                "edition_candidate": {
                    "sapl_record_url": "https://sapl.natal.rn.leg.br/norma/8975",
                    "sapl_record_publication_date": "2025-12-16",
                    "pdf_colophon_publication_date": "2025-12-17",
                },
            },
            "Art. 1º Os arts. 20 passam a vigorar com a seguinte redação:\n“Art. 20. Redação modificadora com conteúdo adicional. ....................”\nArt. 2º Outro dispositivo.",
        ),
    ]
    for index, (source_kind, ref, url, metadata, text) in enumerate(source_specs, start=1):
        document = DocumentoNormativo.objects.create(
            document_key=uuid4().hex,
            source_kind=source_kind,
            source_ref=f"qa:candidate-timeline:{ref}",
            archive_sha256=str(index + 20).zfill(64)
            if source_kind == DocumentoNormativo.SourceKind.ARCHIVE
            else "",
            entry_index=index if source_kind == DocumentoNormativo.SourceKind.ARCHIVE else None,
            original_filename=f"{ref}.pdf",
            content_sha256=str(index).zfill(64),
            official_url=url,
            metadata_json=metadata,
            review_status=DocumentoNormativo.ReviewStatus.PENDING,
        )
        ExtracaoDocumento.objects.create(
            documento=document,
            extractor_version=f"timeline-test-{ref}",
            policy_fingerprint=str(index + 10).zfill(64),
            text_version="legal-text-v1",
            legal_text=text,
            page_count=1,
            page_map_json=[{"start": 0, "end": len(text), "page": index}],
            status=ExtracaoDocumento.Status.COMPLETE,
        )

    relation_candidate = {
        "source_label": "Lei Complementar nº 271/2025",
        "target_scope": "article",
        "target_device": "artigo 20",
        "review_state": "revisão jurídica pendente",
        "action_quote": "passam a vigorar",
        "target_text": "arts. 20, 23 e 25 da Lei nº 3.882/1989",
        "page": 1,
        "pdf_url": "https://sapl.natal.rn.leg.br/media/sapl/public/normajuridica/2025/8975/lei_complementar_no_271_2025.pdf#page=1",
    }
    with patch(
        "src.apps.legislation.workspace_views._pgm_ctm_art20_relation_candidate",
        return_value=relation_candidate,
    ):
        timeline = _pgm_ctm_art20_candidate_timeline(user=AnonymousUser())

    assert timeline["complete"] is True
    assert timeline["snapshot_texts_match"] is True
    assert timeline["amendment_differs_from_2024"] is True
    assert [row["state"] for row in timeline["rows"]] == ["candidate"] * 4
    assert [row["evidence"]["page"] for row in timeline["rows"]] == [1, 2, 3, 4]
    assert timeline["rows"][3]["evidence"]["omitted_following_text"] is True
    assert timeline["rows"][3]["relation_evidence"] == relation_candidate
    publication = timeline["rows"][3]["publication_evidence"]
    assert publication["date"] == date(2025, 12, 16)
    assert publication["sapl_record_date"] == "2025-12-16"
    assert publication["sapl_date_matches_dom"] is True
    assert publication["pdf_colophon_date"] == "2025-12-17"
    assert publication["pdf_colophon_differs"] is True
    assert publication["initial_effective_date"] == date(2025, 12, 16)
    assert publication["initial_effective_date_basis"] == (
        "Art. 6º: vigência na data da publicação"
    )
    assert publication["url"].endswith("dom_20251216_extra_f56130954932a6ec421028e3224ffc68.pdf")
    assert timeline["rows"][3]["official_record_url"] == "https://sapl.natal.rn.leg.br/norma/8975"
    assert not timeline["rows"][3]["evidence"]["quote"].endswith("....................")
    assert any(part["kind"] == "omitted" for part in timeline["textual_diff"])
    assert all(
        "Seção II Do Contribuinte" not in row["evidence"]["quote"]
        for row in timeline["rows"][:3]
    )
    assert any(part["kind"] == "removed" and "anterior" in part["text"] for part in timeline["textual_diff"])
    assert any(part["kind"] == "added" and "modificadora" in part["text"] for part in timeline["textual_diff"])
    assert any(part["kind"] == "same" and "Redação" in part["text"] for part in timeline["textual_diff"])


def test_ctm_lc271_change_set_compares_all_twelve_named_articles_without_claiming_consolidation():
    targets = ("20", "23", "25", "41", "61", "64", "66", "68", "103", "104", "150", "158")
    old_text = "\n".join(
        f"Art. {number}. Texto anterior do dispositivo {number}."
        for number in targets
    )
    replacement_text = (
        "Art. 1º Os artigos do CTM passam a vigorar com nova redação: “"
        + " ........................................................… ".join(
            (
                f"Art. {number}. ........................................................… "
                "§ 6º Texto atualizado do dispositivo 23."
                if number == "23"
                else f"Art. {number}. Texto atualizado do dispositivo {number}."
            )
            for number in targets
        )
        + "”\nArt. 2º Esta Lei entra em vigor."
    )
    docs = []
    for source_kind, identity_key, edition, text in (
        (
            DocumentoNormativo.SourceKind.ARCHIVE,
            "BR-RN-NATAL|lei|municipal_lo|3882|1989",
            {"kind": "official_consolidated_text", "declared_value_year": 2024},
            old_text,
        ),
        (
            DocumentoNormativo.SourceKind.SAPL,
            "BR-RN-NATAL|lei_complementar|municipal_lc|271|2025",
            {},
            replacement_text,
        ),
    ):
        document = DocumentoNormativo.objects.create(
            document_key=uuid4().hex,
            source_kind=source_kind,
            source_ref=f"qa:ctm-change-set:{identity_key}",
            archive_sha256=uuid4().hex.ljust(64, "0")
            if source_kind == DocumentoNormativo.SourceKind.ARCHIVE
            else "",
            entry_index=1 if source_kind == DocumentoNormativo.SourceKind.ARCHIVE else None,
            original_filename="ctm.pdf",
            content_sha256=uuid4().hex.ljust(64, "0"),
            official_url="https://sapl.natal.rn.leg.br/test.pdf",
            metadata_json={"identity_key": identity_key, **({"edition_candidate": edition} if edition else {})},
            review_status=DocumentoNormativo.ReviewStatus.PENDING,
        )
        ExtracaoDocumento.objects.create(
            documento=document,
            extractor_version="ctm-change-set-test",
            policy_fingerprint=uuid4().hex.ljust(64, "0"),
            text_version="legal-text-v1",
            legal_text=text,
            page_count=1,
            page_map_json=[{"start": 0, "end": len(text), "page": 1}],
            status=ExtracaoDocumento.Status.COMPLETE,
        )
        docs.append(document)

    with patch(
        "src.apps.legislation.workspace_views._pgm_document_pdf_url",
        return_value="https://example.test/source.pdf#page=1",
    ):
        result = _pgm_ctm_lc271_change_set(user=AnonymousUser())

    assert result["target_count"] == 12
    assert result["source_pair_count"] == 12
    assert result["complete_pair_count"] == 11
    assert result["all_source_pairs_found"] is True
    assert result["review_pending"] is True
    assert [item["article_number"] for item in result["changes"]] == list(targets)
    assert all(item["state"] == "sources_found" for item in result["changes"])
    assert "Texto anterior do dispositivo 20" in result["changes"][0]["before"]["quote"]
    assert "Texto atualizado do dispositivo 20" in result["changes"][0]["after"]["quote"]
    assert any(part["kind"] == "removed" for part in result["changes"][0]["diff"])
    assert any(part["kind"] == "added" for part in result["changes"][0]["diff"])
    assert result["changes"][1]["after"]["omitted_following_text"] is True
    assert result["changes"][1]["full_text_diff_available"] is False
    assert result["changes"][1]["diff"] == []
    assert all(document.review_status == DocumentoNormativo.ReviewStatus.PENDING for document in docs)


def test_article_150_consolidation_preserves_omitted_caput_and_replaces_unique_paragraph():
    result = build_article_150_snapshot(
        "Art. 150 - A restituição é atualizada monetariamente com base nos mesmos índices. "
        "Parágrafo único - A incidência observa a data de ingresso do pedido.",
        "Art. 150. ........................................................ "
        "--- Página 4 --- ESTADO DO RIO GRANDE DO NORTE CÂMARA MUNICIPAL DE NATAL "
        "Parágrafo único. A incidência da atualização observa como termo inicial, "
        "para fins de cálculo, a data do pagamento indevido. "
        "........................................................................",
    )

    assert result["status"] == "candidate_integrated"
    assert result["preserved_units"] == ["caput"]
    assert result["replaced_units"] == ["Parágrafo único"]
    assert "base nos mesmos índices" in result["text"]
    assert "data do pagamento indevido" in result["text"]
    assert "data de ingresso do pedido" not in result["text"]
    assert "CÂMARA MUNICIPAL" not in result["text"]


def test_article_150_consolidation_fails_closed_when_base_has_ambiguous_paragraphs():
    result = build_article_150_snapshot(
        "Art. 150. Caput. Parágrafo único. Texto A. Parágrafo único. Texto B.",
        "Art. 150. ....... Parágrafo único. Texto novo. .......",
    )

    assert result["status"] == "incomplete"
    assert result["text"] == ""


def test_article_23_consolidation_appends_only_explicit_new_paragraph_to_complete_base():
    before = (
        "Art. 23. Base de cálculo. § 1º Regra um. § 2º Regra dois. "
        "§ 3º Regra três. § 4º Regra quatro (Incluído pela LC 217). "
        "§ 5º Regra cinco, conforme o § 2º."
    )
    amendment = (
        "Art. 23. ........................................................ "
        "§ 6º A base de cálculo poderá ser revisada conforme os arts. 24 e 25."
    )

    result = build_article_23_snapshot(before, amendment)

    assert result["status"] == "candidate_integrated"
    assert result["preserved_units"] == ["Art. 23 da edição municipal de 2024", "§§ 1º–5º"]
    assert result["added_units"] == ["§ 6º"]
    assert result["text"] == f"{before}\n§ 6º A base de cálculo poderá ser revisada conforme os arts. 24 e 25."


def test_article_23_consolidation_fails_closed_if_any_baseline_paragraph_is_missing():
    result = build_article_23_snapshot(
        "Art. 23. Base. § 1º Um. § 2º Dois. § 3º Três. § 5º Cinco.",
        "Art. 23. ................................ § 6º Texto novo.",
    )

    assert result["status"] == "incomplete"
    assert result["text"] == ""


def test_lc271_preview_integrates_only_complete_replacement_and_safe_article_150_merge():
    previews = build_lc271_consolidation_previews([
        {
            "article_number": "20",
            "before": {"quote": "Art. 20. Anterior."},
            "after": {"quote": "Art. 20. Texto integral novo."},
        },
        {
            "article_number": "23",
            "before": {"quote": "Art. 23. Base com lacuna estrutural."},
            "after": {"quote": "Art. 23. .... § 6º Texto."},
        },
        {
            "article_number": "150",
            "before": {
                "quote": "Art. 150. Caput preservado. Parágrafo único. Data antiga."
            },
            "after": {
                "quote": "Art. 150. .... Parágrafo único. Data nova. ........"
            },
        },
    ])

    assert [item["article_number"] for item in previews] == ["20", "150"]
    assert "Art. 20. Texto integral novo." in previews[0]["text"]
    assert "Caput preservado" in previews[1]["text"]
    assert "Data nova" in previews[1]["text"]


def test_lc271_explicit_effects_include_repeals_and_exclude_unpromulgated_proposals():
    effects = lc271_effects_summary()

    assert effects["additions"] == ["133-A", "133-B", "133-C", "133-D", "133-E"]
    assert "Lei nº 3.882/1989, Art. 66, § 11" in effects["express_repeals"]
    assert "Lei nº 3.882/1989, Art. 68, § 1º" in effects["express_repeals"]
    assert "LC 16/2026" not in str(effects)


def test_lc271_added_articles_extracts_only_five_complete_devices():
    source = (
        "Art. 2º Ficam acrescidos os artigos 133-A, 133-B, 133-C, 133-D e 133-E "
        "à Lei nº 3.882/1989, com a seguinte redação:\n“\n"
        "Art. 133-A. Texto completo A.\n"
        "Art. 133-B. Texto completo B.\n"
        "Art. 133-C. Texto completo C; conforme o art. 133-B.\n"
        "Art. 133-D. Texto completo D.\n"
        "Art. 133-E. Texto completo E.”\n"
        "Art. 3º Os arts. 7º e 25 da LC 141/2014."
    )

    articles = extract_lc271_added_articles(source)

    assert [item["article_number"] for item in articles] == [
        "133-A", "133-B", "133-C", "133-D", "133-E"
    ]
    assert articles[0]["text"] == "Art. 133-A. Texto completo A."
    assert articles[-1]["text"] == "Art. 133-E. Texto completo E."
    assert extract_lc271_added_articles(source.replace("Texto completo C;", "...")) == []


def test_lc55_original_article_context_never_fabricates_missing_extraction():
    assert _pgm_lc55_original_article_context({}, user=AnonymousUser()) is None

    context = _pgm_lc55_original_article_context(
        {
            "evidence": {"quote": "Art. 34 — trecho literal do PDF.", "page": 7},
            "document": None,
            "extraction": None,
        },
        user=AnonymousUser(),
    )

    assert context["quote"] == "Art. 34 — trecho literal do PDF."
    assert context["page"] == 7
    assert context["document"] is None


def test_pgm_lc55_timeline_shows_unavailable_original_text_without_fake_page_anchor():
    official_pdf_url = (
        "https://www2.natal.rn.gov.br/bvn/publicacoes/lei_complementar_n_055.pdf"
    )
    request = RequestFactory().get("/explorar/demo-consolidacao/")
    request.user = AnonymousUser()
    body = render_to_string(
        "legislation/workspace/pgm_consolidation_demo.html",
        {
            "lc55_article_34_original": None,
            "lc55_original_official_pdf_url": official_pdf_url,
            "lc55_history": [],
        },
        request=request,
    )

    assert "O trecho do Art. 34 não foi localizado em uma extração nesta instância" in body
    assert f'href="{official_pdf_url}"' in body
    assert "#page=9" not in body
    assert "A Licença Ambiental observa as seguintes etapas" not in body


def test_pgm_demo_discloses_missing_lc55_candidate_without_claiming_comparison():
    request = RequestFactory().get("/explorar/demo-consolidacao/")
    request.user = AnonymousUser()
    body = render_to_string(
        "legislation/workspace/pgm_consolidation_demo.html",
        {
            "old_article_21": None,
            "lc55_evidence_document": None,
            "lc55_original_official_pdf_url": (
                "https://www2.natal.rn.gov.br/bvn/publicacoes/lei_complementar_n_055.pdf"
            ),
        },
        request=request,
    )

    assert (
        "O PDF candidato da LC nº 55/2004 não está disponível nesta instância. "
        "A menção no Art. 260 da LC nº 258/2024 é mostrada como referência textual, "
        "sem cotejo do conteúdo do Art. 21."
    ) in body


def test_pgm_demo_does_not_select_duplicate_archive_identity_automatically():
    candidates = [
        SimpleNamespace(metadata_json={"identity_candidate": {"type": "lei"}}),
        SimpleNamespace(metadata_json={"identity_candidate": {"type": "lei"}}),
    ]

    result = classify_identity_candidates(candidates, "lei")

    assert result["state"] == "ambiguous"
    assert result["document"] is None
    assert result["conflicts"] == []
    assert result["ambiguous_candidates"] == candidates


def test_pgm_demo_keeps_truncated_identity_candidates_ambiguous():
    candidates = [
        SimpleNamespace(metadata_json={"identity_candidate": {"type": "lei"}})
        for _ in range(8)
    ]

    result = classify_identity_candidates(candidates, "lei", truncated=True)

    assert result["state"] == "ambiguous"
    assert result["document"] is None
    assert len(result["ambiguous_candidates"]) == 8
    assert result["candidate_list_truncated"] is True


def test_pgm_demo_distinguishes_species_conflicts_from_matching_candidate():
    exact = SimpleNamespace(metadata_json={"identity_candidate": {"type": "lei"}})
    wrong_type = SimpleNamespace(
        metadata_json={"identity_candidate": {"type": "lei_complementar"}}
    )

    exact_result = classify_identity_candidates([exact, wrong_type], "lei")
    conflict_result = classify_identity_candidates([wrong_type], "lei")

    assert exact_result["state"] == "candidate"
    assert exact_result["document"] is exact
    assert exact_result["conflicts"] == [wrong_type]
    assert conflict_result["state"] == "identity_conflict"
    assert conflict_result["document"] is None


def test_pgm_candidate_review_link_requires_active_staff_permission():
    document = SimpleNamespace(public_id=uuid4())
    anonymous_url = _pgm_document_review_url(document, AnonymousUser())
    unauthorized_staff = SimpleNamespace(
        is_authenticated=True,
        is_active=True,
        is_staff=True,
        has_perm=lambda permission: False,
    )
    authorized_reviewer = SimpleNamespace(
        is_authenticated=True,
        is_active=True,
        is_staff=True,
        has_perm=lambda permission: permission == "legislation.view_documentonormativo",
    )

    assert anonymous_url is None
    assert _pgm_document_review_url(document, unauthorized_staff) is None
    assert _pgm_document_review_url(document, authorized_reviewer) == reverse(
        "legislation:document_evidence", args=(document.public_id,)
    )


def test_pgm_source_links_use_official_sapl_pdf_for_pending_official_candidates():
    document = SimpleNamespace(
        source_kind=DocumentoNormativo.SourceKind.SAPL,
        official_url="https://sapl.natal.rn.leg.br/media/sapl/public/normajuridica/2024/4052/lc.pdf",
        norma_id=1,
        norma=SimpleNamespace(pdf_url="https://sapl.natal.rn.leg.br/norma/4052"),
        public_id=uuid4(),
    )

    assert _pgm_document_pdf_url(document, 59) == (
        "https://sapl.natal.rn.leg.br/media/sapl/public/normajuridica/2024/4052/lc.pdf#page=59"
    )


def test_pgm_source_links_do_not_expose_missing_local_candidate_pdfs(monkeypatch):
    from src.apps.legislation import workspace_views

    document = SimpleNamespace(
        source_kind=DocumentoNormativo.SourceKind.ARCHIVE,
        review_status=DocumentoNormativo.ReviewStatus.PENDING,
        public_id=uuid4(),
    )
    monkeypatch.setattr(workspace_views, "local_pdf_available", lambda _document: False)
    assert _pgm_document_pdf_url(document, 8) is None

    monkeypatch.setattr(workspace_views, "local_pdf_available", lambda _document: True)
    # A pending archive PDF must not produce a dead link for anonymous users.
    assert _pgm_document_pdf_url(document, 8, user=AnonymousUser()) is None
    with override_settings(DEBUG=True, NORMATIVE_ARCHIVE_REVIEW_UI_ENABLED=True):
        assert _pgm_document_pdf_url(document, 8, user=AnonymousUser()) == (
            f"/normas/documentos/{document.public_id}/pdf/#page=8"
        )

    reviewer = SimpleNamespace(
        is_authenticated=True,
        is_active=True,
        is_staff=True,
        has_perm=lambda permission: permission == "legislation.view_documentonormativo",
    )
    assert _pgm_document_pdf_url(document, 8) is None
    assert _pgm_document_pdf_url(document, 8, user=reviewer) == (
        f"/normas/documentos/{document.public_id}/pdf/#page=8"
    )


def test_settings_exposes_source_freshness_to_staff_only(client):
    anonymous = client.get("/configuracoes/").content.decode()
    assert "Atualização das fontes" not in anonymous

    staff = get_user_model().objects.create_user(
        username="source-health-staff",
        password="qa-password",
        is_staff=True,
    )
    client.force_login(staff)
    response = client.get("/configuracoes/")
    body = response.content.decode()

    assert response.status_code == 200
    assert "Atualização das fontes" in body
    assert "SAPL · legislação municipal" in body
    assert "Diário Oficial do Município" in body
    assert "Nenhuma sincronização registrada" in body
    assert "não comprovam que o corpus esteja completo" in body


def test_settings_explains_overlapping_scope_counts_for_degraded_source(client):
    staff = get_user_model().objects.create_user(
        username="source-health-scope-staff",
        password="qa-password",
        is_staff=True,
    )
    client.force_login(staff)
    sapl_report = {
        "status": "degraded",
        "scope_count": 1,
        "full_sweep_scope_count": 0,
        "partial_scope_count": 1,
        "uninitialized_scope_count": 1,
        "failed_scope_count": 0,
        "stale_scope_count": 1,
        "stale_incremental_scope_count": 1,
        "stale_full_sweep_scope_count": 0,
        "last_success_at": None,
    }
    dom_report = {
        "status": "stale",
        "scope_count": 2,
        "full_sweep_scope_count": 2,
        "partial_scope_count": 0,
        "uninitialized_scope_count": 0,
        "failed_scope_count": 0,
        "stale_scope_count": 1,
        "stale_incremental_scope_count": 0,
        "stale_full_sweep_scope_count": 1,
        "last_success_at": None,
    }

    with patch(
        "src.apps.ingestion.source_sync_health.get_source_sync_health",
        side_effect=[sapl_report, dom_report],
    ):
        response = client.get("/configuracoes/")

    body = response.content.decode()
    assert response.status_code == 200
    assert "Escopos acompanhados: 1" in body
    assert "varreduras completas do catálogo: 0" in body
    assert "parciais: 1" in body
    assert "sem conclusão registrada: 1" in body
    assert "sucessos incrementais vencidos: 1" in body
    assert "varreduras completas vencidas: 0" in body
    assert "Os indicadores podem se sobrepor" in body
    assert "Escopos acompanhados: 2" in body
    assert "varreduras completas do catálogo: 2" in body
    assert "sucessos incrementais vencidos: 0" in body
    assert "varreduras completas vencidas: 1" in body


def test_history_search_ranks_bag_of_words_relevance_before_recency():
    recent_weak = SimpleNamespace(
        title="Consulta recente",
        history_messages=[SimpleNamespace(content="Assunto geral")],
        updated_at=2,
    )
    relevant_old = SimpleNamespace(
        title="Política de imóveis abandonados",
        history_messages=[
            SimpleNamespace(content="Lei municipal sobre imóveis abandonados e revitalização")
        ],
        updated_at=1,
    )
    assert _rank_history([recent_weak, relevant_old], "imóveis abandonados") == [relevant_old]


def test_history_preview_uses_first_user_question_not_a_recent_answer():
    user = get_user_model().objects.create_user(username="history-preview", password="pass")
    session = ChatSession.objects.create(user=user, title="Resumo gerado")
    ChatMessage.objects.create(session=session, role="user", content="Pergunta inicial distinta")
    ChatMessage.objects.create(session=session, role="assistant", content="Resposta inicial")
    for index in range(11):
        ChatMessage.objects.create(
            session=session, role="user", content=f"Pergunta posterior {index}"
        )
        ChatMessage.objects.create(
            session=session, role="assistant", content=f"Resposta posterior {index}"
        )
    client = Client()
    client.force_login(user)

    response = client.get("/historico/")

    assert response.status_code == 200
    body = response.content.decode()
    assert "Pergunta inicial distinta" in body
    assert "Resposta inicial" not in body


@pytest.fixture
def norma():
    return Norma.objects.create(
        tipo="Lei",
        numero="123",
        ano=2026,
        status="consolidated",
        ementa="Norma de teste",
        texto_original="Art. 1º Texto.",
        texto_consolidado="Lei nº 123/2026\nArt. 1º Texto.",
    )


def test_workspace_surfaces_render_without_server_errors(norma):
    client = Client()
    urls = [
        "/",
        "/assistente/",
        "/normas/",
        "/pesquisa/",
        "/explorar/",
        "/conferir/",
        "/colecoes/",
        "/historico/",
        "/configuracoes/",
        f"/normas/{norma.pk}/",
        f"/normas/{norma.pk}/compare/",
        f"/normas/{norma.pk}/tree/",
        "/api/v1/normas/",
    ]
    for url in urls:
        response = client.get(url, follow=True)
        assert response.status_code == 200, url
        assert b"Server Error" not in response.content
        assert b"Traceback" not in response.content


def test_norma_detail_does_not_claim_currently_in_force_when_corpus_completeness_is_unknown():
    norma = Norma.objects.create(
        tipo="Lei",
        numero="8206",
        ano=2026,
        status="consolidated",
        data_publicacao="2026-09-21",
        data_vigencia="2026-09-21",
        texto_consolidado="Art. 1º Texto.",
    )
    CorpusRevision.objects.update_or_create(
        key="municipal",
        defaults={
            "completeness": "unknown",
            "digest": "a" * 64,
            "norm_count": 1,
            "device_count": 1,
        },
    )

    response = Client().get(f"/normas/{norma.pk}/")
    body = response.content.decode()

    assert response.status_code == 200
    assert "Situação atual não verificada no corpus" in body
    assert "Data cadastral não revisada" in body
    assert "Data de publicação cadastrada · não revisada" in body
    assert "não confirmam publicação nem vigência" in body
    assert '<span class="badge badge-success">Vigente</span>' not in body


def test_pending_norma_detail_does_not_call_the_record_consolidated():
    norma = Norma.objects.create(
        tipo="Lei",
        numero="9001",
        ano=2020,
        status="pending",
        texto_original="Art. 1º Texto sintético.",
    )

    body = Client().get(f"/normas/{norma.pk}/").content.decode("utf-8")

    assert "Norma municipal" in body
    assert '<span class="badge badge-success">Consolidada</span>' not in body


def test_norma_detail_explicitly_labels_synthetic_qa_fixture():
    norma = Norma.objects.create(
        tipo="Lei",
        numero="9001",
        ano=2020,
        status="pending",
        texto_original="Art. 5º O prazo é de dez dias.",
    )
    document = DocumentoNormativo.objects.create(
        document_key="b" * 64,
        norma=norma,
        source_kind=DocumentoNormativo.SourceKind.LEGACY,
        source_ref="jurix-synthetic-qa:test",
        original_filename="[SINTÉTICO QA] Lei 9001/2020.pdf",
        content_sha256="c" * 64,
        metadata_json={"synthetic": True},
    )
    norma.documento_base = document
    norma.save(update_fields=["documento_base"])

    body = Client().get(f"/normas/{norma.pk}/").content.decode("utf-8")

    assert "Fixture sintética de QA." in body
    assert "não representa uma norma real nem uma validação jurídica" in body

    comparison = Client().get(
        f"/normas/{norma.pk}/compare/?from_as_of=2020-01-01&to_as_of=2020-01-02"
    ).content.decode("utf-8")
    assert "Fixture sintética de QA." in comparison
    assert "não representa uma norma real nem uma validação jurídica" in comparison


def test_collections_and_assistant_copy_describe_only_available_products():
    anonymous = Client()
    collections = anonymous.get("/colecoes/").content.decode()
    assistant = anonymous.get("/assistente/").content.decode()

    assert "normas municipais salvas" in collections
    assert "normas e evidências" not in collections
    assert "legislação municipal" in assistant
    assert "jurisprudência..." not in assistant

    user = get_user_model().objects.create_user(username="collections-copy", password="pass")
    authenticated = Client()
    authenticated.force_login(user)
    assert (
        "Adicione normas municipais à coleção" in authenticated.get("/colecoes/").content.decode()
    )


def test_workspace_uses_local_system_fonts_regardless_of_google_fonts_csp_opt_in():
    client = Client()
    routes = ("/assistente/", "/normas/", "/configuracoes/")
    with override_settings(CSP_ALLOW_GOOGLE_FONTS=False):
        for route in routes:
            response = client.get(route)
            assert response.status_code == 200
            assert b"fonts.googleapis.com" not in response.content
            assert b"fonts.gstatic.com" not in response.content
            assert "fonts.googleapis.com" not in response["Content-Security-Policy"]

    with override_settings(CSP_ALLOW_GOOGLE_FONTS=True):
        for route in routes:
            response = client.get(route)
            assert response.status_code == 200
            assert b"fonts.googleapis.com" not in response.content
            assert b"fonts.gstatic.com" not in response.content

    styles = Path("src/apps/core/static/css/jurix-figma.css").read_text(encoding="utf-8")
    assert "--font-sans: system-ui" in styles
    assert "--font-serif: Georgia" in styles


def test_product_root_enters_the_assistant_flow():
    response = Client().get("/")
    assert response.status_code == 302
    assert response["Location"] == "/assistente/"


def test_anonymous_assistant_get_does_not_create_session_state_or_chat_records():
    client = Client()

    assert client.get("/assistente/").status_code == 200
    assert client.get("/assistente/").status_code == 200
    assert "temp_chat_session_id" not in client.session
    assert "temp_chat_messages" not in client.session
    assert ChatSession.objects.count() == 0


@override_settings(NORMATIVE_ARCHIVE_ASSISTANT_ENABLED=True)
def test_assistant_discloses_unconfigured_official_updates_without_overstating_coverage(client):
    with patch(
        "src.apps.ingestion.source_sync_health.get_source_sync_health",
        return_value={"status": "not_configured"},
    ) as source_health, patch(
        "src.apps.operations.worker_health.get_normative_worker_health",
        return_value={"status": "current", "responding_workers": 1, "queue_workers": 1},
    ):
        archive_response = client.get("/assistente/?corpus=archive-qa")
        standard_response = client.get("/assistente/")

    archive_body = archive_response.content.decode()
    standard_body = standard_response.content.decode()
    assert archive_response.status_code == 200
    assert "A atualização do SAPL e do Diário Oficial não está configurada" in archive_body
    assert "a cobertura das fontes pode estar incompleta" in archive_body
    assert "Atualização das fontes" in standard_body
    assert "A atualização do SAPL e do Diário Oficial não está configurada" in standard_body
    assert source_health.call_count == 4


@override_settings(NORMATIVE_ARCHIVE_ASSISTANT_ENABLED=True)
def test_assistant_discloses_degraded_source_freshness_without_calling_it_unconfigured(client):
    with patch(
        "src.apps.ingestion.source_sync_health.get_source_sync_health",
        side_effect=[
            {"status": "degraded"}, {"status": "current"},
            {"status": "degraded"}, {"status": "current"},
        ],
    ) as source_health, patch(
        "src.apps.operations.worker_health.get_normative_worker_health",
        return_value={"status": "current", "responding_workers": 1, "queue_workers": 1},
    ):
        standard_response = client.get("/assistente/")
        archive_response = client.get("/assistente/?corpus=archive-qa")

    standard_body = standard_response.content.decode()
    archive_body = archive_response.content.decode()
    expected_notice = "A atualização de uma ou mais fontes oficiais não está confirmada"

    assert standard_response.status_code == 200
    assert archive_response.status_code == 200
    assert "Atualização das fontes" in standard_body
    assert expected_notice in standard_body
    assert "Acervo histórico local" in archive_body
    assert expected_notice in archive_body
    assert "não está configurada neste ambiente" not in standard_body
    assert "não está configurada neste ambiente" not in archive_body
    assert source_health.call_count == 4


@override_settings(NORMATIVE_ARCHIVE_ASSISTANT_ENABLED=True)
def test_assistant_warns_that_archive_may_become_stale_when_update_queue_is_down(client):
    with patch(
        "src.apps.ingestion.source_sync_health.get_source_sync_health",
        return_value={"status": "current"},
    ), patch(
        "src.apps.operations.worker_health.get_normative_worker_health",
        return_value={"status": "queue_missing", "responding_workers": 1, "queue_workers": 0},
    ) as queue_health:
        standard_response = client.get("/assistente/")
        archive_response = client.get("/assistente/?corpus=archive-qa")

    expected_notice = "A fila de atualização das fontes oficiais não está disponível"
    for response in (standard_response, archive_response):
        body = response.content.decode()
        assert response.status_code == 200
        assert expected_notice in body
        assert "o acervo pode ficar desatualizado" in body
        assert "Confira a fonte oficial" in body
    archive_body = archive_response.content.decode()
    assert 'class="anonymous-banner jurix-anonymous-banner jurix-corpus-notice"' in archive_body
    assert 'data-corpus-notice="archive"' in archive_body
    assert "Acervo histórico local — extrações pendentes de revisão." in archive_body
    assert "Atualização do acervo não confirmada." in archive_body
    assert "Este aviso descreve a sincronização geral do SAPL e do Diário Oficial" in archive_body
    assert "não confirma a publicação de cada documento citado" in archive_body
    assert "Metadados e segmentação estão sob revisão" in archive_body
    assert queue_health.call_count == 2


@override_settings(NORMATIVE_ARCHIVE_ASSISTANT_ENABLED=True)
def test_assistant_hides_source_health_exception_details(client):
    with patch(
        "src.apps.ingestion.source_sync_health.get_source_sync_health",
        side_effect=RuntimeError("private database hostname"),
    ):
        response = client.get("/assistente/")

    body = response.content.decode()
    assert response.status_code == 200
    assert "Não foi possível confirmar a atualização das fontes oficiais" in body
    assert "private database hostname" not in body


def test_assistant_omits_source_warning_when_all_configured_sources_are_current(client):
    with patch(
        "src.apps.ingestion.source_sync_health.get_source_sync_health",
        return_value={"status": "current"},
    ) as source_health, patch(
        "src.apps.operations.worker_health.get_normative_worker_health",
        return_value={"status": "current", "responding_workers": 1, "queue_workers": 1},
    ):
        response = client.get("/assistente/")

    body = response.content.decode()
    assert response.status_code == 200
    assert "Atualização das fontes" not in body
    assert "não está configurada neste ambiente" not in body
    assert source_health.call_count == 2


def test_authenticated_assistant_get_does_not_change_active_session():
    user = get_user_model().objects.create_user(username="assistant-get", password="pass")
    active = ChatSession.objects.create(user=user, title="Ativa", is_active=True)
    inactive = ChatSession.objects.create(user=user, title="Inativa", is_active=False)
    client = Client()
    client.force_login(user)

    assert client.get(f"/assistente/{inactive.slug}/").status_code == 200
    assert client.get(f"/assistente/{inactive.slug}/").status_code == 200
    active.refresh_from_db()
    inactive.refresh_from_db()

    assert active.is_active is True
    assert inactive.is_active is False
    assert ChatSession.objects.filter(user=user).count() == 2


def test_semantic_search_empty_state_omits_none_year_from_catalog_link():
    response = Client().get("/pesquisa/", {"q": "x" * 201})
    body = response.content.decode("utf-8")

    assert response.status_code == 200
    assert "Buscar no acervo normativo" in body
    assert "&amp;ano=" in body
    assert "ano=None" not in body


def test_exact_normative_search_not_found_uses_nonsemantic_empty_state():
    response = Client().get("/pesquisa/", {"q": "Lei nº 9001/2020"})
    body = response.content.decode("utf-8")

    assert response.status_code == 200
    assert "Nenhum texto pesquisável localizado para esta referência" in body
    assert "Referência exata não localizada nos resultados pesquisáveis desta instância." not in body
    assert "Consultar acervo normativo e catálogo SAPL" in body
    assert "Isso não prova que a norma inexista" in body
    assert "fora do staging" in body
    assert "Nenhuma correspondência semântica encontrada." not in body


@override_settings(
    DEBUG=True,
    NORMATIVE_ARCHIVE_ENABLED=True,
    NORMATIVE_ARCHIVE_REVIEW_UI_ENABLED=True,
)
def test_exact_normative_search_with_archive_candidate_is_not_shown_as_error(client):
    DocumentoNormativo.objects.create(
        document_key="d" * 64,
        source_kind=DocumentoNormativo.SourceKind.ARCHIVE,
        source_ref="archive:qa-fixture:entry:1202010",
        entry_index=1202010,
        original_filename="LeiComplementar_120_2010.pdf",
        content_sha256="e" * 64,
        metadata_json={
            "identity_candidate": {
                "type": "lei_complementar",
                "number": "120",
                "year": 2010,
            }
        },
        review_status=DocumentoNormativo.ReviewStatus.PENDING,
    )
    from src.processing.document_search import search_archive_documents

    assert search_archive_documents("Lei Complementar nº 120/2010")["count"] == 1

    response = client.get("/pesquisa/", {"q": "Lei Complementar nº 120/2010"})
    body = response.content.decode("utf-8")

    assert response.status_code == 200
    assert "Acervo histórico local" in body
    assert "Referência normativa exata não localizada" not in body
    assert 'class="workspace-alert"' not in body
    assert "Referência ainda não consolidada" in body
    assert "A busca encontrou 1 PDF candidato no acervo histórico" in body
    assert "1 documento candidato" in body
    assert "Lei Complementar nº 120/2010" in body
    assert "Lei Complementar nº 120 /2010" not in body
    assert "LeiComplementar_120_2010.pdf" in body


def test_history_page_paginates_authenticated_sessions():
    user = get_user_model().objects.create_user(username="history-page", password="pass")
    ChatSession.objects.bulk_create(
        [ChatSession(user=user, title=f"Conversa {index}") for index in range(21)]
    )
    client = Client()
    assert client.login(username="history-page", password="pass")

    first = client.get("/historico/")
    second = client.get("/historico/?page=2")

    assert first.status_code == second.status_code == 200
    first_body = first.content.decode("utf-8")
    second_body = second.content.decode("utf-8")
    assert "Próxima" in first_body
    assert "Anterior" in second_body
    assert first.content.count(b"data-history-card") == 20
    assert second.content.count(b"data-history-card") == 1
    assert b"data-history-delete" in first.content
    assert (
        "csrftoken" in client.cookies
    ), "History deletion needs the CSRF cookie for its API request"


def test_norma_surfaces_expose_consistent_identity(norma):
    client = Client()
    for url in (
        f"/normas/{norma.pk}/",
        f"/normas/{norma.pk}/compare/",
        f"/normas/{norma.pk}/tree/",
    ):
        response = client.get(url)
        body = response.content.decode()
        assert "Lei" in body
        assert "123" in body
        assert "2026" in body


def test_norma_list_corpus_total_matches_current_database(norma):
    response = Client().get("/normas/")
    body = response.content.decode()
    assert "<title>Normas e acervo — Jurix</title>" in body
    assert '<h1 id="normas-title" class="jurix-norma-title">Normas e acervo</h1>' in body
    assert 'placeholder="Número ou tema"' in body
    assert 'class="jurix-norma-stat-value">1<' in body
    assert 'class="jurix-norma-stat-label">normas consolidadas<' in body
    assert 'class="jurix-norma-stat-label">resultados<' in body


def test_norma_search_surfaces_sapl_metadata_separately_from_consolidated_law():
    Norma.objects.create(
        tipo="Lei",
        numero="8206",
        ano=2026,
        status="pending",
        ementa="Institui programa municipal de educação.",
        sapl_id=9387,
        sapl_url="https://sapl.natal.rn.leg.br/norma/9387",
        sapl_metadata={
            "_jurix_source_hash": "qa-catalog-hash",
            "_jurix_type_catalog": {
                "raw_code": "1",
                "raw_label": "LEI ORDINÁRIA",
                "type_key": "lei",
                "known": True,
            },
        },
    )

    response = Client().get("/normas/?q=8206")

    assert response.status_code == 200
    body = response.content.decode()
    assert 'class="jurix-norma-stat-value">0<' in body
    assert "normas consolidadas" in body
    assert "Referências encontradas no SAPL" in body
    assert "Lei Ordinária nº 8206/2026" in body
    assert "Ementa registrada no SAPL" in body
    assert "texto não integrado" in body
    assert "não comprovam o conteúdo integral" in body.casefold()
    assert 'href="https://sapl.natal.rn.leg.br/norma/9387"' in body
    assert 'href="/normas/1/"' not in body


def test_explore_page_explains_empty_reviewed_graph_without_promoting_archive_candidates():
    with override_settings(NORMATIVE_ARCHIVE_ENABLED=True, NORMATIVE_GRAPH_ENABLED=True):
        response = Client().get("/explorar/")

    body = response.content.decode()
    assert response.status_code == 200
    assert "Nenhuma norma consolidada disponível para explorar." in body
    assert "PDFs em revisão" in body
    assert "Buscar no acervo local" in body
    assert 'aria-label="Filtrar normas para exploração"' not in body


def test_pgm_consolidation_preview_is_hidden_when_qa_flag_is_disabled():
    with override_settings(DEBUG=True, PGM_CONSOLIDATION_DEMO_ENABLED=False):
        response = Client().get("/explorar/demo-consolidacao/")

    assert response.status_code == 404


def test_pgm_consolidation_demo_renders_device_level_draft_with_review_caveats():
    request = RequestFactory().get("/explorar/demo-consolidacao/")
    request.user = AnonymousUser()
    body = render_to_string(
        "legislation/workspace/pgm_consolidation_demo.html",
        {
            "lc55_history": [
                {
                    "source_label": "LC nº 173/2017 · Art. 2º",
                    "state": "candidate",
                    "document": {"original_filename": "lc173.pdf", "get_review_status_display": lambda: "pendente"},
                    "evidence": {"quote": "Acrescenta os §§ 3º e 4º ao Art. 34.", "page": 1},
                    "pdf_url": "/documentos/lc173.pdf#page=1",
                    "official_pdf_url": "https://natal.rn.gov.br/storage/app/media/legislacao/anexos/LeiComplementar_20171229_173_.pdf",
                    "official_hash_match": True,
                },
                {
                    "source_label": "LC nº 185/2019 · Art. 87",
                    "state": "candidate",
                    "document": {"original_filename": "lc185.pdf", "get_review_status_display": lambda: "pendente"},
                    "evidence": {"quote": "Art. 87 dá nova redação ao Art. 34.", "page": 20},
                    "pdf_url": "/documentos/lc185.pdf#page=20",
                    "official_pdf_url": "https://natal.rn.gov.br/storage/app/media/legislacao/anexos/LeiComplementar_20190718_185_.pdf",
                    "official_hash_match": True,
                },
                {
                    "source_label": "Compilação oficial municipal · julho/2019 (snapshot, não ato)",
                    "state": "snapshot",
                    "document": None,
                    "evidence": {"quote": "§ 3º, § 4º e § 5º compilados.", "page": 16},
                    "pdf_url": "https://www.natal.rn.gov.br/storage/app/media/semurb/legislacao/35_Codigo_Obras_Atualizado_Julho_2019.pdf",
                },
                {
                    "source_label": "LC nº 258/2024 · Art. 260, IV",
                    "state": "candidate",
                    "document": {"original_filename": "lc258.pdf", "get_review_status_display": lambda: "pendente"},
                    "evidence": {"quote": "Art. 260, IV — Lei Complementar nº 055 de 27 de janeiro de 2004", "page": 59},
                    "pdf_url": "/documentos/lc258.pdf#page=59",
                },
            ],
            "lc258_publication_date": date(2024, 12, 27),
            "lc258_effective_date": date(2025, 3, 27),
            "lc258_dom_issue_url": (
                "https://www2.natal.rn.gov.br/_anexos/publicacao/dom/"
                "dom_20241227_extra_0aaf5ad445c342a04c28c91e2275c838.pdf"
            ),
            "lc55_baseline_pdf_url": "/documentos/lc55-julho-2019.pdf",
            "lc55_article_34_original": {
                "quote": "Art. 34 — texto promulgado; §§ 1º e 2º.",
                "page": 9,
                "pdf_url": "https://www2.natal.rn.gov.br/bvn/publicacoes/lei_complementar_n_055.pdf#page=9",
            },
            "lc55_paragraph_3_2017": {
                "quote": "§ 3º — texto de 2017.",
                "page": 1,
            },
            "lc55_paragraph_4_2017": {
                "quote": "§ 4º — texto candidato de 2017.",
                "page": 1,
            },
            "lc55_paragraph_3_2019": {
                "quote": "§ 3º — texto da compilação oficial de 2019.",
                "page": 16,
            },
            "lc55_paragraph_4_2019": {"quote": "§ 4º — texto oficial de 2019.", "page": 16},
            "lc55_paragraph_5_2019": {"quote": "§ 5º — acrescido pela LC 185/2019.", "page": 16},
            "lc55_paragraph_3_comparison": "mismatch",
            "lc55_history_185": {
                "pdf_url": "/documentos/lc185.pdf#page=20",
                "official_pdf_url": "https://natal.rn.gov.br/storage/app/media/legislacao/anexos/LeiComplementar_20190718_185_.pdf",
            },
            "lc55_replacement_article_34_2019": {
                "quote": "Art. 34 A licença ambiental observa as seguintes etapas: ... § 3º. Texto novo.",
                "page": 20,
            },
            "lc55_paragraph_3_185": {"quote": "§ 3º. Texto novo.", "page": 20},
            "lc55_article_34_2019_snapshot": {
                "quote": "Art. 34 compilado em julho de 2019, §§ 1º a 5º.",
                "page": 16,
            },
            "lc258_new_article_14": {"quote": "Texto novo do Art. 14", "page": 59},
            "lc261_replacement_article_18_paragraph_2": {
                "quote": "Texto novo do § 2º",
                "target": "LC 208/2022, Art. 18, § 2º",
                "page": 35,
            },
            "lc261_article_117": {"quote": "Art. 117. Revogam-se...", "page": 34},
            "lc261_article_118": {"quote": "Art. 118...", "page": 34},
            "lc261_repeal_targets": [
                {
                    "source_device": "Inciso I",
                    "target_text": "Art. 21 e Anexo A da Lei Municipal nº 208",
                    "citation": "Lei nº 208/2022, Art. 21",
                    "expected_type": "Lei",
                    "state": "identity_conflict",
                    "documents": [
                        {
                            "type_display": "Lei Complementar",
                            "filename": "lc208.pdf",
                            "pdf_url": "/normas/documentos/lc208-candidate/pdf/",
                            "official_url": "",
                            "matches_expected_type": False,
                        }
                    ],
                    "sapl_url": "https://sapl.natal.rn.leg.br/norma/1160",
                    "sapl_type_display": "Lei Complementar",
                    "sapl_publication_date": "08/03/2022",
                    "source_pdf_url": "https://sapl.natal.rn.leg.br/media/lc261.pdf#page=34",
                },
                {
                    "source_device": "Inciso II",
                    "target_text": "Lei Municipal nº 4.664/1995",
                    "citation": "Lei nº 4.664/1995",
                    "expected_type": "Lei",
                    "state": "not_found",
                    "documents": [
                        {
                            "type_display": "Lei",
                            "filename": "lei-4664-candidate.pdf",
                            "pdf_url": "",
                            "pdf_access_required": True,
                            "official_url": "",
                            "matches_expected_type": True,
                        }
                    ],
                    "sapl_url": "",
                    "sapl_type_display": "",
                    "sapl_publication_date": "",
                    "source_pdf_url": "https://sapl.natal.rn.leg.br/media/lc261.pdf#page=34",
                },
            ],
            "lc258_article_261_pdf_url": "https://example.test/lc258.pdf#page=59",
            "lc208_article_14_pdf_url": "https://example.test/lc208.pdf#page=8",
            "lc261_article_118_pdf_url": "https://example.test/lc261.pdf#page=35",
            "lc208_article_18_pdf_url": "https://example.test/lc208.pdf#page=10",
            "lc261_pdf_url": "https://example.test/lc261.pdf#page=34",
            "lc208_article_21_pdf_url": "https://example.test/lc208.pdf#page=11",
            "source_segmentation_count": 0,
            "ctm_art20_candidate_timeline": {
                "complete": True,
                "snapshot_texts_match": True,
                "amendment_differs_from_2024": True,
                "textual_diff": [
                    {"kind": "same", "text": "texto "},
                    {"kind": "removed", "text": "antigo"},
                    {"kind": "added", "text": "novo"},
                ],
                "rows": [
                    {
                        "key": "snapshot_2021",
                        "label": "Consolidação municipal · exercício 2021",
                        "state": "candidate",
                        "evidence": {"quote": "Art. 20. Texto antigo.", "page": 13},
                        "pdf_url": "/candidate/2021.pdf#page=13",
                        "official_pdf_url": "https://www.natal.rn.gov.br/2021.pdf",
                    },
                    {
                        "key": "snapshot_2022",
                        "label": "Consolidação municipal · exercício 2022",
                        "state": "candidate",
                        "evidence": {"quote": "Art. 20. Texto antigo.", "page": 15},
                        "pdf_url": "/candidate/2022.pdf#page=15",
                        "official_pdf_url": "https://www.natal.rn.gov.br/2022.pdf",
                    },
                    {
                        "key": "snapshot_2024",
                        "label": "Consolidação municipal · exercício 2024",
                        "state": "candidate",
                        "evidence": {"quote": "Art. 20. Texto antigo.", "page": 17},
                        "pdf_url": "/candidate/2024.pdf#page=17",
                        "official_pdf_url": "https://www.natal.rn.gov.br/2024.pdf",
                    },
                    {
                        "key": "amendment_2025",
                        "label": "LC nº 271/2025 · Art. 1º",
                        "state": "candidate",
                        "evidence": {"quote": "Art. 20. Texto novo.", "page": 1},
                        "publication_evidence": {
                            "date": date(2025, 12, 16),
                            "issue": "Diário Oficial do Município nº 5935 · edição extra",
                            "url": "https://natal.rn.gov.br/dom-5935.pdf",
                            "sapl_record_date": "2025-12-16",
                            "pdf_colophon_date": "2025-12-17",
                            "initial_effective_date": date(2025, 12, 16),
                        },
                        "pdf_url": "/candidate/271.pdf#page=1",
                        "official_pdf_url": "https://sapl.natal.rn.leg.br/271.pdf",
                    },
                ],
            },
            "pending_proposal_watch": {
                "title": "PLC nº 12/2025 — alteração proposta ao Art. 59 da LC 258/2024",
                "matter_url": "https://sapl.natal.rn.leg.br/materia/48759",
                "opinion_url": "https://sapl.natal.rn.leg.br/materia/56868",
                "checked_on": "15/10/2026",
                "status": "Em tramitação no SAPL",
                "latest_event": "Parecer nº 993/2026, apresentado em 03/08/2026.",
            },
            "references": [
                {
                    "state": "missing",
                    "roman": "II",
                    "citation": "Lei nº 4.566 de 19 de maio de 1992",
                    "reference_scope": {"kind": "act", "label": "Ato citado"},
                    "sapl_registry": {
                        "status": "year_conflict",
                        "checked_on": "2026-10-15",
                        "reference_year": 1992,
                        "reference_date": "1992-05-19",
                        "reference_date_display": "19/05/1992",
                        "records": [
                            {
                                "sapl_id": 6491,
                                "number": "4566",
                                "year": 1994,
                                "type_display": "Lei Ordinária",
                                "date_display": "27/08/1994",
                                "url": "https://sapl.natal.rn.leg.br/norma/6491",
                            }
                        ],
                        "official_sources": [
                            {
                                "source": "Biblioteca Virtual do Natal (BVN)",
                                "title": "Lei nº 4.566/1992 — ficha bibliográfica",
                                "url": "https://www2.natal.rn.gov.br/bvn/detalheBVN.php?valorRegistro=1871",
                                "document_url": "https://www2.natal.rn.gov.br/bvn/publicacoes/lei_4.566.pdf",
                                "date_display": "19/05/1992",
                                "note": "O PDF usa ‘decreto’ em dois dispositivos; revisar.",
                            }
                        ],
                    },
                },
                {
                    "state": "candidate",
                    "roman": "VI",
                    "citation": "Lei Promulgada nº 562 de 14 de setembro de 2018",
                    "reference_scope": {"kind": "act", "label": "Ato citado"},
                    "document": {"original_filename": "lp_562.18.pdf"},
                    "pdf_url": "",
                    "review_url": "/normas/documentos/a2334a00-772f-4b38-9153-c88ba13ebe5b/",
                    "sapl_registry": {"status": "date_matched_candidate", "records": []},
                },
                {
                    "state": "identity_conflict",
                    "roman": "VII",
                    "citation": "Lei nº 198 de 12 de novembro de 2021",
                    "expected_type_display": "Lei",
                    "reference_scope": {"kind": "act", "label": "Ato citado"},
                    "conflicts": [
                        {
                            "candidate_type": "Lei Complementar",
                            "document": {"original_filename": "LeiComplementar_20211220_198_.pdf"},
                            "pdf_url": "",
                        },
                        {
                            "candidate_type": "Lei Complementar",
                            "document": {"original_filename": "plc_006.21-convertido.pdf"},
                            "pdf_url": "/normas/documentos/sapl-lc198/pdf/",
                        },
                    ],
                    "sapl_registry": {"status": "identity_conflict", "records": []},
                },
                {
                    "state": "ambiguous",
                    "roman": "VIII",
                    "citation": "Lei nº 700/2020",
                    "reference_scope": {"kind": "act", "label": "Ato citado"},
                    "ambiguous_candidates": [
                        {
                            "candidate_type": "Lei",
                            "document": {"original_filename": "lei-700-a.pdf"},
                            "pdf_url": "",
                        },
                        {
                            "candidate_type": "Lei",
                            "document": {"original_filename": "lei-700-b.pdf"},
                            "pdf_url": "",
                        },
                    ],
                    "candidate_list_truncated": False,
                    "sapl_registry": {"status": "ambiguous", "records": []},
                },
            ],
        },
        request=request,
    )
    assert "Minuta de consolidação textual por dispositivo" in body
    assert body.count('class="pgm-demo__target-evidence"') == 4
    assert 'aria-label="Abrir detalhes da identificação e documentos de Lei nº 4.566 de 19 de maio de 1992"' in body
    assert "Ver evidências e documentos" in body
    assert "PDF candidato correspondente" in body
    assert "Art. 20 da Lei nº 3.882/1989" in body
    assert "Consolidação municipal · exercício 2021" in body
    assert "Consolidação municipal · exercício 2022" in body
    assert "Consolidação municipal · exercício 2024" in body
    assert "LC nº 271/2025 · Art. 1º" in body
    assert "Redação integrada candidata · Art. 20 em 16/12/2025" in body
    assert "Art. 20. Texto novo." in body
    assert "Marco temporal inicial confirmado em fonte oficial" in body
    assert "16/12/2025" in body
    assert 'href="https://natal.rn.gov.br/dom-5935.pdf#page=1"' in body
    assert "o colofão da cópia PDF hospedada no SAPL informa 2025-12-17" in body
    assert "O texto extraído do Art. 20 nas edições de 2021, 2022 e 2024 coincide." in body
    assert "difere textualmente do recorte de 2024" in body
    assert "Isto não certifica publicação, eficácia, completude de alterações posteriores ou vigência atual" in body
    assert "0 dispositivos documentais persistidos" in body
    assert "segmentação e a identidade da fonte ainda exigem revisão" in body
    assert "Redação substitutiva da LC 258/2024, Art. 261" in body
    assert "Redação substitutiva da LC 261/2025, Art. 118" in body
    assert 'href="https://example.test/lc208.pdf#page=10"' in body
    assert 'href="https://example.test/lc261.pdf#page=35"' in body
    assert "Fonte oficial · LC 261/2025, Art. 118, PDF p. 35" in body
    assert "Conferir Art. 118 no PDF, p. 35" in body
    assert (
        'href="https://example.test/lc208.pdf#page=10" target="_blank" '
        'rel="noopener noreferrer">Abrir PDF candidato da LC 208/2022, Art. 18,'
        in body
    )
    assert "Art. 21 e Anexo A · identidade a confirmar" in body
    assert "não é snapshot aceito nem certificação de vigência" in body
    assert "associação à LC 208/2022 é candidata" in body
    assert "Fonte oficial municipal localizada · candidata para revisão" in body
    assert "PDF não integrado ao lote QA · fonte oficial candidata disponível" in body
    assert "Expanda os detalhes do catálogo para abrir a fonte oficial candidata" in body
    assert "O documento candidato foi identificado, mas o PDF local não está disponível nesta sessão." in body
    assert 'href="" target="_blank" rel="noopener noreferrer">Conferir PDF no acervo' not in body
    assert "Candidato identificado como Lei Complementar · PDF indisponível nesta sessão" in body
    assert body.count("PDF candidato identificado como Lei · indisponível nesta sessão") == 2
    assert 'href="" target="_blank" rel="noopener noreferrer">Inspecionar candidato' not in body
    assert "Alvos nomeados pela LC 261/2025, Art. 117" in body
    assert "PDF local candidato disponível apenas para revisor autenticado." in body
    assert "Conflito de espécie ou cadastro; associação não confirmada." in body
    assert 'href="https://sapl.natal.rn.leg.br/norma/1160"' in body
    assert 'href="/normas/documentos/lc208-candidate/pdf/"' in body
    assert "Proposta legislativa pendente — não incorporada à consolidação nem ao RAG" in body
    assert "A proposta não é tratada como alteração promulgada nem como redação vigente." in body
    assert "Cotejo textual · edição 2024 × redação transcrita em 2025" in body
    assert "Trecho presente na edição 2024" in body
    assert "Trecho presente na redação transcrita pela LC 271/2025" in body
    assert "<del>antigo</del>" in body
    assert "<ins>novo</ins>" in body
    assert 'href="https://sapl.natal.rn.leg.br/materia/48759"' in body
    assert 'href="https://sapl.natal.rn.leg.br/materia/56868"' in body
    assert "O PDF usa ‘decreto’ em dois dispositivos; revisar." in body
    assert "Candidato identificado como Lei Complementar · PDF indisponível nesta sessão" in body
    assert 'href="/normas/documentos/sapl-lc198/pdf/"' in body
    assert 'href="/normas/documentos/sapl-lc198/pdf/"' in body
    assert "LeiComplementar_20211220_198_.pdf" in body
    assert "plc_006.21-convertido.pdf" in body
    assert 'href="https://www2.natal.rn.gov.br/bvn/publicacoes/lei_4.566.pdf"' in body
    assert "Revisar identidade e extração no Jurix (área restrita)" in body
    assert 'href="/normas/documentos/a2334a00-772f-4b38-9153-c88ba13ebe5b/"' in body
    assert "O que aconteceu com a LC nº 55/2004?" in body
    assert "A extração candidata do original indica que o Art. 34 contém os §§ 1º e 2º" in body
    assert "Art. 34 — texto promulgado; §§ 1º e 2º." in body
    assert 'href="https://www2.natal.rn.gov.br/bvn/publicacoes/lei_complementar_n_055.pdf#page=9"' in body
    assert 'lei_complementar_n_055.pdf#page=9#page=9' not in body
    assert "LC nº 173/2017 · Art. 2º" in body
    assert "LC nº 185/2019 · Art. 87" in body
    assert "Art. 34, § 3º · LC 185/2019, Art. 87" in body
    assert "Integridade da cópia confirmada: SHA-256 idêntico ao PDF do portal oficial." in body
    assert "Snapshot oficial municipal · julho/2019 · divergência pendente" in body
    assert "Art. 34 compilado em julho de 2019, §§ 1º a 5º." in body
    assert "O Art. 87 da LC 185/2019 diz expressamente" in body
    assert 'href="https://natal.rn.gov.br/storage/app/media/legislacao/anexos/LeiComplementar_20190718_185_.pdf#page=20"' in body
    assert "Compilação oficial municipal · julho/2019 (snapshot, não ato)" in body
    assert "LC nº 258/2024 · Art. 260, IV" in body
    assert "Art. 34, § 3º · LC 173/2017, Art. 2º" in body
    assert "Art. 34, § 3º · LC 185/2019, Art. 87" in body
    assert "§ 3º — texto de 2017." in body
    assert "Art. 34 compilado em julho de 2019, §§ 1º a 5º." in body
    assert "§ 4º na compilação oficial de 2019" in body
    assert "§ 5º na compilação oficial de 2019" in body
    assert "há divergência material: o Art. 87 da LC 185/2019 imprime a regra das micro e pequenas empresas como § 3º" in body
    assert "registra a regra das micro e pequenas empresas como § 5º" in body
    assert "não é seguro publicar uma redação consolidada final do Art. 34 ainda" in body
    assert "a identidade do PDF da lei foi conferida pelo hash da cópia oficial" in body
    assert "Decreto municipal nº 11.681/2018" in body
    assert "LC 173/2018" in body
    assert "27/12/2024" in body
    assert 'datetime="2025-03-27">27/03/2025</time>' in body
    assert "Status temporal para triagem do procurador" in body
    assert "Regra geral:" in body
    assert "revoga expressamente a LC nº 55/2004" in body
    assert "Exceção de transição:" in body
    assert "se o processo foi protocolado antes de 27/03/2025" in body
    assert "não exibimos uma redação consolidada desse artigo como se estivesse revisada" in body
    assert "O Art. 260, IV, da LC 258/2024 inclui a LC 55/2004 na cláusula" in body
    assert "A edição extra nº 5615 do Diário Oficial confirma a publicação da LC 258 em 27/12/2024" in body
    assert "a data geral calculada é" in body
    assert "https://www2.natal.rn.gov.br/_anexos/publicacao/dom/dom_20241227_extra_0aaf5ad445c342a04c28c91e2275c838.pdf" in body
    assert 'href="https://www2.natal.rn.gov.br/_anexos/publicacao/dom/dom_20241227_extra_0aaf5ad445c342a04c28c91e2275c838.pdf#page=17"' in body
    assert "edição extra nº 5615 do DOM, p. 17 (publicação da LC 258)" in body
    assert "A edição do Diário Oficial correspondente não foi confirmada nesta verificação" not in body
    assert "esta data calculada não certifica o início dos efeitos jurídicos" not in body
    assert "A lista do Art. 260, IV, inclui expressamente a LC 55/2004" in body
    assert "A partir daí, o Art. 260, IV, revoga expressamente" not in body
    assert "até a entrada em vigor e ainda sem despacho decisório" in body
    assert "eventual opção formal" in body
    assert 'href="https://www.planalto.gov.br/ccivil_03/leis/lcp/lcp95.htm"' in body
    assert "Divergência de identidade para revisão" in body
    assert "a intenção da referência" in body
    assert 'href="https://sapl.natal.rn.leg.br/norma/925"' in body
    assert 'href="/documentos/lc173.pdf#page=1"' in body
    assert 'href="https://www.natal.rn.gov.br/storage/app/media/semurb/legislacao/35_Codigo_Obras_Atualizado_Julho_2019.pdf"' in body


def test_pgm_lc55_chain_does_not_select_duplicate_pending_source_documents():
    first = SimpleNamespace()
    second = SimpleNamespace()
    candidates = SimpleNamespace(order_by=lambda *args: [first, second])

    with patch.object(DocumentoNormativo.objects, "filter", return_value=candidates):
        result = _pgm_lc55_chain_candidate("identity", "2", "LC 173/2017 · Art. 2º")

    assert result["state"] == "ambiguous"
    assert result["document"] is None
    assert result["evidence"] is None


def test_pgm_original_lc55_quote_cleans_only_display_artifacts():
    quote = (
        "Art. 34 - Etapas: I – Prévia (LP); 202 II – Instalação (LI); "
        "§ 1o - Prazo próprio. § 2º -. O Executivo define as condições."
    )

    cleaned = _pgm_clean_extracted_legal_quote(quote)

    assert "202" not in cleaned
    assert "§ 1º — Prazo próprio." in cleaned
    assert "§ 2º — O Executivo" in cleaned
    assert "Art. 34" in cleaned and "Instalação (LI)" in cleaned


def test_pgm_consolidation_preview_entry_point_requires_explicit_qa_flag():
    with override_settings(
        DEBUG=True,
        NORMATIVE_GRAPH_ENABLED=True,
        PGM_CONSOLIDATION_DEMO_ENABLED=True,
    ):
        response = Client().get("/explorar/")

    assert response.status_code == 200
    assert b"demo-consolidacao/" in response.content
    assert b"/explorar/demo-consolidacao/" in response.content
    assert "sete referências expressas de revogação" in response.content.decode()
    assert "Abrir grafo demonstrativo da LC 258/2024" in response.content.decode()
    assert "relação entre dois PDFs candidatos" not in response.content.decode()


def test_pgm_case_sapl_snapshot_keeps_exact_mismatch_duplicate_and_unchecked_distinct():
    with override_settings(SAPL_BASE_URL="https://sapl.natal.rn.leg.br/api"):
        exact = _pgm_lc258_sapl_registry_evidence("4885", 1997, "lei")
        type_conflict = _pgm_lc258_sapl_registry_evidence("1894", 1969, "lei_complementar")
        dated_conflict = _pgm_lc258_sapl_registry_evidence(
            "1894", 1969, "lei_complementar", date(1969, 12, 31)
        )
        duplicate = _pgm_lc258_sapl_registry_evidence("562", 2018, "lei_promulgada")
        date_matched = _pgm_lc258_sapl_registry_evidence(
            "562", 2018, "lei_promulgada", date(2018, 9, 14)
        )
        mismatch = _pgm_lc258_sapl_registry_evidence("198", 2021, "lei")
        year_conflict = _pgm_lc258_sapl_registry_evidence("4566", 1992, "lei")
        year_conflict_with_bvn = _pgm_lc258_sapl_registry_evidence(
            "4566", 1992, "lei", date(1992, 5, 19)
        )
        identity_conflict = _pgm_lc258_sapl_registry_evidence(
            "275", 2009, "lei_promulgada"
        )

    assert exact["status"] == "exact_identity_candidate"
    assert exact["records"][0]["url"] == "https://sapl.natal.rn.leg.br/norma/6817"
    assert exact["official_sources"][0]["source"] == "Biblioteca Virtual do Natal (BVN)"
    assert "Decreto nº 8.227/2007 separado" in exact["official_sources"][0]["note"]
    assert exact["official_sources"][0]["document_url"].endswith(
        "ritur_relatorio_de_impacto_sobre_trafego_urbano.pdf"
    )
    assert type_conflict["status"] == "species_conflict"
    assert type_conflict["records"][0]["type_display"] == "Lei Ordinária"
    assert type_conflict["official_sources"][0]["source"] == (
        "Biblioteca Virtual do Natal / SEMURB"
    )
    assert "denomina Lei Complementar" in type_conflict["official_sources"][0]["note"]
    assert type_conflict["official_sources"][0]["document_url"].endswith(
        "/lei_n_1.894_69.pdf"
    )
    assert dated_conflict["status"] == "species_conflict"
    assert dated_conflict["reference_date_display"] == "31/12/1969"
    assert dated_conflict["records"][0]["date_display"] == "25/12/1969"
    assert dated_conflict["records"][0]["reference_date_match"] is False
    assert duplicate["status"] == "ambiguous"
    assert {row["sapl_id"] for row in duplicate["records"]} == {254, 9202}
    assert date_matched["status"] == "date_matched_candidate"
    assert [row["sapl_id"] for row in date_matched["records"]] == [254, 9202]
    assert [row["reference_date_match"] for row in date_matched["records"]] == [True, False]
    assert date_matched["records"][0]["date_display"] == "14/09/2018"
    assert date_matched["official_sources"][0]["source"].startswith("SAPL Natal")
    assert "Art. 13 prevê vigência na data da publicação" in date_matched["official_sources"][0]["note"]
    assert date_matched["official_sources"][0]["document_url"].endswith("/2018/254/lp_562.18.pdf")
    assert mismatch["status"] == "species_conflict"
    assert mismatch["records"][0]["type_display"] == "Lei Complementar"
    assert mismatch["official_sources"][0]["source"].startswith("SAPL Natal")
    assert "deixa número/data do cabeçalho em branco" in mismatch["official_sources"][0]["note"]
    assert mismatch["official_sources"][0]["document_url"].endswith(
        "/plc_006.21-convertido.pdf"
    )
    assert year_conflict["status"] == "year_conflict"
    assert year_conflict["records"][0]["year"] == 1994
    assert year_conflict["records"][0]["year_match"] is False
    assert year_conflict["records"][0]["url"] == "https://sapl.natal.rn.leg.br/norma/6491"
    assert year_conflict_with_bvn["status"] == "year_conflict"
    assert year_conflict_with_bvn["reference_date_display"] == "19/05/1992"
    assert year_conflict_with_bvn["official_sources"][0]["source"] == (
        "Biblioteca Virtual do Natal (BVN)"
    )
    assert "decreto" in year_conflict_with_bvn["official_sources"][0]["note"]
    assert year_conflict_with_bvn["official_sources"][0]["document_url"].endswith(
        "/lei_4.566.pdf"
    )
    assert identity_conflict["status"] == "identity_conflict"
    assert identity_conflict["records"][0]["type_display"] == "Lei Complementar"
    assert identity_conflict["records"][0]["year"] == 2026
    assert identity_conflict["official_sources"][0]["source"] == (
        "Diário Oficial do Município de Natal"
    )
    assert "17/03/2009" in identity_conflict["official_sources"][0]["date_display"]
    assert identity_conflict["official_sources"][0]["document_url"].endswith(
        "dom_20090317.pdf"
    )


def test_pgm_citation_date_parser_reads_portuguese_dates_and_rejects_invalid_dates():
    assert _pgm_citation_date("Lei Promulgada nº 562 de 14 de setembro de 2018") == date(
        2018, 9, 14
    )
    assert _pgm_citation_date("Lei nº 562 de 31 de fevereiro de 2018") is None
    assert _pgm_citation_date("Lei nº 562/2018") is None


def test_pgm_repeal_graph_parser_extracts_each_roman_reference_without_merging_items():
    article = """Art. 260. Ficam revogados:
I - Lei Complementar nº 1.894 de 31 de dezembro de 1969;
II - Lei nº 4.566 de 19 de maio de 1992;
III - Lei nº 4.885 de 07 de outubro de 1997;
IV - Lei Complementar nº 055 de 27 de janeiro de 2004;
V - Art. 21 da Lei Promulgada nº 275 de 12 de março de 2009;
VI - Lei Promulgada nº 562 de 14 de setembro de 2018;
VII - Lei nº 198 de 12 de novembro de 2021.
Art. 261. Próximo dispositivo."""
    source_match, references = _parse_repeal_candidates(article)

    assert source_match is not None
    assert [roman for roman, _ in references] == ["I", "II", "III", "IV", "V", "VI", "VII"]
    assert references[4][1].startswith("Art. 21 da Lei Promulgada nº 275")
    assert references[6][1] == "Lei nº 198 de 12 de novembro de 2021"


def test_pgm_case_evidence_extracts_one_exact_article_and_page_without_promoting_it():
    text = (
        "Art. 21 - Regra antiga de licenciamento.\n"
        "--- Página 8 ---\nCÂMARA MUNICIPAL DE NATAL\n"
        "Art. 22 - Próximo artigo, que não deve entrar no trecho."
    )
    extraction = SimpleNamespace(
        legal_text=text,
        page_map_json=[{"start": 0, "end": len(text), "page": 7}],
    )

    evidence = _pgm_article_evidence(extraction, "21")

    assert evidence["quote"].startswith("Art. 21 - Regra antiga de licenciamento.")
    assert "Art. 22" not in evidence["quote"]
    assert "Página 8" not in evidence["quote"]
    assert evidence["page"] == 7


def test_pgm_article_evidence_accepts_ordinal_article_number():
    text = "Art. 2º - Acrescenta §§ 3º e 4º ao Art. 34.\nArt. 3º - Vigência."
    extraction = SimpleNamespace(
        legal_text=text,
        page_map_json=[{"start": 0, "end": len(text), "page": 1}],
    )

    evidence = _pgm_article_evidence(extraction, "2")

    assert evidence == {
        "quote": "Art. 2º - Acrescenta §§ 3º e 4º ao Art. 34.",
        "page": 1,
    }


def test_pgm_article_evidence_removes_lc208_page_footer_but_keeps_following_paragraph():
    text = (
        "Art.14. Texto inicial.\n§ 3º VETADO\n--- Página 8 ---\n"
        "PALÁCIO FELIPE CAMARÃO\nRua Ulisses Caldas, 81, Centro, 59025-090\n"
        "(84) 3232.8845, www.natal.rn.gov.br\n§ 4º Texto normativo que continua o artigo.\n"
        "Art. 15. Próximo artigo."
    )
    extraction = SimpleNamespace(
        legal_text=text,
        page_map_json=[{"start": 0, "end": len(text), "page": 8}],
    )

    evidence = _pgm_article_evidence(extraction, "14")

    assert "Art. 15" not in evidence["quote"]
    assert "§ 4º Texto normativo que continua o artigo." in evidence["quote"]
    assert "PALÁCIO FELIPE CAMARÃO" not in evidence["quote"]
    assert "Rua Ulisses Caldas" not in evidence["quote"]
    assert "www.natal.rn.gov.br" not in evidence["quote"]


def test_pgm_final_article_stops_before_session_colophon_and_publication_metadata():
    text = (
        "Art. 266. Esta Lei entra em vigor após 90 dias da publicação.\n"
        "Sala das Sessões, em Natal, 27 de dezembro de 2024.\n"
        "Presidente da Câmara. Publicada no Diário Oficial do Município em: 27/12/2024.\n"
        "Autoria: Poder Executivo. ANEXO I - tabela extensa."
    )
    extraction = SimpleNamespace(
        legal_text=text,
        page_map_json=[{"start": 0, "end": len(text), "page": 61}],
    )

    evidence = _pgm_article_evidence(extraction, "266")

    assert evidence == {
        "quote": "Art. 266. Esta Lei entra em vigor após 90 dias da publicação.",
        "page": 61,
    }

    annex_only_text = "Art. 266. Esta Lei entra em vigor após 90 dias.\nANEXO I - tabela extensa."
    annex_only = SimpleNamespace(
        legal_text=annex_only_text,
        page_map_json=[{"start": 0, "end": len(annex_only_text), "page": 61}],
    )
    annex_evidence = _pgm_article_evidence(annex_only, "266")

    assert annex_evidence == {
        "quote": "Art. 266. Esta Lei entra em vigor após 90 dias.",
        "page": 61,
    }

    prefecture_text = (
        "Art. 266. Esta Lei entra em vigor 90 dias após a data de sua publicação, "
        "revogadas as disposições em contrário. Palácio Felipe Camarão, em Natal, "
        "27 de dezembro de 2024. Prefeito. ANEXO I - dimensões dos ambientes."
    )
    prefecture = SimpleNamespace(
        legal_text=prefecture_text,
        page_map_json=[{"start": 0, "end": len(prefecture_text), "page": 61}],
    )
    prefecture_evidence = _pgm_article_evidence(prefecture, "266")

    assert prefecture_evidence == {
        "quote": (
            "Art. 266. Esta Lei entra em vigor 90 dias após a data de sua publicação, "
            "revogadas as disposições em contrário."
        ),
        "page": 61,
    }


def test_pgm_replacement_evidence_extracts_only_the_new_quoted_article():
    text = (
        "Art. 261. O artigo 14 da Lei Complementar nº 208 passa a ter a seguinte redação: "
        "“Art. 14. Redação nova. § 1º Complemento da redação.”\n"
        "Art. 262. Regra de transição."
    )
    extraction = SimpleNamespace(
        legal_text=text,
        page_map_json=[{"start": 0, "end": len(text), "page": 60}],
    )

    evidence = _pgm_replacement_article_evidence(extraction, "261", "14")

    assert evidence == {
        "quote": "Art. 14. Redação nova. § 1º Complemento da redação.",
        "page": 60,
        "omitted_following_text": False,
    }


def test_pgm_replacement_article_evidence_links_to_continuation_page():
    text = (
        "Art. 261. O artigo 14 da LC 208 passa a ter a seguinte redação:\n"
        "“Art. 14. Redação nova do artigo.”\nArt. 262. Regra de transição."
    )
    replacement_start = text.index("Art. 14. Redação nova")
    extraction = SimpleNamespace(
        legal_text=text,
        page_map_json=[
            {"start": 0, "end": replacement_start, "page": 59},
            {"start": replacement_start, "end": len(text), "page": 60},
        ],
    )

    evidence = _pgm_replacement_article_evidence(extraction, "261", "14")

    assert evidence == {
        "quote": "Art. 14. Redação nova do artigo.",
        "page": 60,
        "omitted_following_text": False,
    }


def test_pgm_replacement_article_evidence_stops_at_next_dotted_replacement():
    text = (
        "Art. 1º Os arts. 20 e 23 passam a vigorar com nova redação: "
        "“Art. 20. Caput completo. Parágrafo único completo. "
        "................................................................… Art. 23. "
        "................................................................… § 6º Trecho alterado. "
        ".................................................................… Art. 25. Outro texto.’\n"
        "Art. 2º Vigência."
    )
    extraction = SimpleNamespace(
        legal_text=text,
        page_map_json=[{"start": 0, "end": len(text), "page": 1}],
    )

    article_20 = _pgm_replacement_article_evidence(extraction, "1", "20")
    article_23 = _pgm_replacement_article_evidence(extraction, "1", "23")

    assert article_20 == {
        "quote": "Art. 20. Caput completo. Parágrafo único completo.",
        "page": 1,
        "omitted_following_text": False,
    }
    assert article_23 is not None
    assert article_23["quote"].startswith("Art. 23.")
    assert "Art. 25." not in article_23["quote"]
    assert "§ 6º Trecho alterado." in article_23["quote"]
    assert article_23["omitted_following_text"] is True


def test_pgm_paragraph_evidence_extracts_only_the_requested_paragraph():
    text = (
        "Art. 18. Caput.\n§ 1º Primeiro parágrafo.\n"
        "§ 2º Texto anterior que continua.\n§ 3º Próximo parágrafo.\n"
        "Art. 19. Outro dispositivo."
    )
    extraction = SimpleNamespace(
        legal_text=text,
        page_map_json=[{"start": 0, "end": len(text), "page": 12}],
    )

    evidence = _pgm_paragraph_evidence(extraction, "18", "2")

    assert evidence == {"quote": "§ 2º Texto anterior que continua.", "page": 12}


def test_pgm_paragraph_evidence_links_to_page_where_paragraph_text_starts():
    text = (
        "Art. 18. Caput.\n§ 1º Primeiro parágrafo.\n"
        "§ 2º Texto anterior que continua na página seguinte.\n"
        "§ 3º Próximo parágrafo.\nArt. 19. Outro dispositivo."
    )
    paragraph_start = text.index("§ 2º")
    extraction = SimpleNamespace(
        legal_text=text,
        page_map_json=[
            {"start": 0, "end": paragraph_start, "page": 10},
            {"start": paragraph_start, "end": len(text), "page": 11},
        ],
    )

    evidence = _pgm_paragraph_evidence(extraction, "18", "2")

    assert evidence == {
        "quote": "§ 2º Texto anterior que continua na página seguinte.",
        "page": 11,
    }


def test_pgm_compare_paragraph_evidence_strips_compilation_provenance_and_flags_wording_diff():
    candidate = {"quote": "§3º - As atividades poderão ser aprovadas."}
    official_snapshot = {
        "quote": "§ 3° – As atividades poderão ser aprovados. (Redação dada pela LC 173/2017)"
    }

    assert _pgm_compare_paragraph_evidence(candidate, official_snapshot) == "mismatch"
    assert _pgm_compare_paragraph_evidence(candidate, None) == "insufficient"
    assert _pgm_compare_paragraph_evidence(
        {"quote": "§3º - Texto igual."},
        {"quote": "§ 3° – Texto igual. (Redação dada pela LC 173/2017)"},
    ) == "match"


def test_pgm_replacement_paragraph_evidence_extracts_new_text_and_target():
    text = (
        "Art. 118. O §2º do Art. 18 da lei complementar 208/2022 passa a vigorar "
        "com a seguinte redação: “Acrescer à Subzona de Uso Restrito os lotes definidos.”\n"
        "Art. 119. Revisão técnica."
    )
    extraction = SimpleNamespace(
        legal_text=text,
        page_map_json=[{"start": 0, "end": len(text), "page": 35}],
    )

    evidence = _pgm_replacement_paragraph_evidence(extraction, "118", "18", "2")

    assert evidence == {
        "target": "§2º do Art. 18 da lei complementar 208/2022",
        "quote": "Acrescer à Subzona de Uso Restrito os lotes definidos.",
        "page": 35,
    }


def test_pgm_replacement_paragraph_evidence_links_to_continuation_page():
    text = (
        "Art. 118. O §2º do Art. 18 da LC 208/2022 passa a vigorar com a seguinte redação:\n"
        "“Acrescer à Subzona de Uso Restrito da ZPA-1 os lotes novos.”\nArt. 119. Vigência."
    )
    replacement_start = text.index("Acrescer à Subzona")
    extraction = SimpleNamespace(
        legal_text=text,
        page_map_json=[
            {"start": 0, "end": replacement_start, "page": 34},
            {"start": replacement_start, "end": len(text), "page": 35},
        ],
    )

    evidence = _pgm_replacement_paragraph_evidence(extraction, "118", "18", "2")

    assert evidence == {
        "target": "§2º do Art. 18 da LC 208/2022",
        "quote": "Acrescer à Subzona de Uso Restrito da ZPA-1 os lotes novos.",
        "page": 35,
    }


def test_pgm_reference_scope_distinguishes_act_from_device_without_claiming_effect():
    act_scope = _pgm_reference_scope("Lei Complementar nº 55/2004")
    device_scope = _pgm_reference_scope("Art. 21 da Lei Promulgada nº 275/2009")

    assert act_scope["kind"] == "act"
    assert act_scope["label"] == "Ato citado"
    assert "não se deve inferir revogação integral" in act_scope["note"]
    assert device_scope["kind"] == "device"
    assert device_scope["label"] == "Dispositivo citado"
    assert "não valida o alcance" in device_scope["note"]


def test_explore_filters_confirmed_topics_and_publication_dates(norma):
    norma.data_publicacao = "2026-04-10"
    norma.ementa = "Programa municipal de educação popular"
    norma.save(update_fields=["data_publicacao", "ementa", "updated_at"])
    topic_code = f"educacao-pgm-test-{uuid4().hex}"
    topic = Topic.objects.create(code=topic_code, label="Educação")
    NormaTopic.objects.create(
        norma=norma,
        topic=topic,
        origin=NormaTopic.Origin.MANUAL,
        status=NormaTopic.Status.CONFIRMED,
    )

    client = Client()
    matching = client.get(f"/explorar/?tema={topic_code}&de=2026-04-01&ate=2026-04-30")
    outside_range = client.get(f"/explorar/?tema={topic_code}&de=2026-05-01")
    invalid_range = client.get("/explorar/?de=2026-05-01&ate=2026-04-01")

    assert matching.status_code == 200 and b"Lei" in matching.content and b"123/2026" in matching.content
    assert b"0 normas" in outside_range.content
    assert "A data inicial não pode ser posterior" in invalid_range.content.decode()
    assert b"123/2026" not in invalid_range.content


def test_explore_resolves_explicit_norm_identity_without_cross_type_or_year_matches(norma):
    norma.numero = "198"
    norma.tipo = "Lei Complementar"
    norma.ano = 2021
    norma.save(update_fields=["numero", "tipo", "ano", "updated_at"])
    Norma.objects.create(tipo="Lei", numero="198", ano=2021, status="consolidated")
    Norma.objects.create(tipo="Lei Complementar", numero="198", ano=2020, status="consolidated")

    response = Client().get("/explorar/?q=Lei+Complementar+198%2F2021")
    body = response.content.decode()

    assert response.status_code == 200
    assert "1 norma" in body
    assert "Lei Complementar nº 198/2021" in body
    assert "Lei nº 198/2021" not in body
    assert "Lei Complementar nº 198/2020" not in body


def test_explore_selection_uses_only_consolidated_norms_and_reuses_public_graph(norma):
    candidate = Norma.objects.create(tipo="Lei", numero="124", ano=2026, status="pending")
    client = Client()
    with override_settings(NORMATIVE_GRAPH_ENABLED=True, NORMATIVE_HISTORY_ENABLED=True):
        selected = client.get(f"/explorar/?norma={norma.pk}")
        hidden = client.get(f"/explorar/?norma={candidate.pk}")

    assert selected.status_code == 200
    assert f"data-api-url=\"/api/v1/normas/{norma.pk}/relations/\"" in selected.content.decode()
    assert "Norma selecionada" in selected.content.decode()
    assert reverse("workspace:normative_casefile", args=[norma.pk]) in selected.content.decode()
    assert "Norma selecionada" not in hidden.content.decode()
    assert "124/2026" not in hidden.content.decode()
    assert reverse("workspace:normative_casefile", args=[candidate.pk]) not in hidden.content.decode()


def test_explore_candidate_relations_are_staff_only_and_preserve_source_scope(norma):
    candidate = Norma.objects.create(tipo="Lei", numero="991234", ano=2095, status="pending")
    document = DocumentoNormativo.objects.create(
        document_key=uuid4().hex,
        norma=candidate,
        source_kind=DocumentoNormativo.SourceKind.ARCHIVE,
        source_ref="jurix-qa:candidate-relations:991234-2095",
        original_filename="[QA] candidato.pdf",
        role=DocumentoNormativo.Role.ORIGINAL,
        content_sha256="a" * 64,
        size_bytes=100,
        review_status=DocumentoNormativo.ReviewStatus.PENDING,
    )
    candidate.documento_base = document
    candidate.save(update_fields=["documento_base", "updated_at"])
    source_device = Dispositivo.objects.create(
        norma=candidate,
        tipo="artigo",
        numero="1º",
        ordem=1,
        texto="[QA] texto de evidência candidata",
    )
    EventoAlteracao.objects.create(
        dispositivo_fonte=source_device,
        acao="ALTERA",
        target_text="[QA] referência a norma existente",
        norma_alvo=norma,
        evidence_json={"quote": "[QA] evidência não revisada", "page": 1},
        target_reference_json={"synthetic_candidate": True},
    )

    with override_settings(NORMATIVE_GRAPH_ENABLED=True):
        anonymous = Client().get("/explorar/?escopo=candidatas")
        public = Client().get("/explorar/")
        denied_user = get_user_model().objects.create_user(
            username=f"candidate-review-partial-{uuid4().hex}",
            password="qa-password",
            is_staff=True,
        )
        denied_user.user_permissions.add(
            Permission.objects.get(content_type__app_label="legislation", codename="view_eventoalteracao")
        )
        denied_client = Client()
        denied_client.force_login(denied_user)
        missing_document_permission = denied_client.get("/explorar/?escopo=candidatas")

        reviewer = get_user_model().objects.create_user(
            username=f"candidate-review-{uuid4().hex}",
            password="qa-password",
            is_staff=True,
        )
        reviewer.user_permissions.add(
            Permission.objects.get(content_type__app_label="legislation", codename="view_eventoalteracao"),
            Permission.objects.get(content_type__app_label="legislation", codename="view_documentonormativo"),
            Permission.objects.get(content_type__app_label="legislation", codename="review_eventonormativocandidato"),
        )
        reviewer_client = Client()
        reviewer_client.force_login(reviewer)
        reviewed_candidates = reviewer_client.get(f"/explorar/?escopo=candidatas&norma={candidate.pk}")

    assert anonymous.status_code == 403
    assert missing_document_permission.status_code == 403
    assert public.status_code == 200
    assert "991234/2095" not in public.content.decode()
    body = reviewed_candidates.content.decode()
    assert reviewed_candidates.status_code == 200
    assert "Modo restrito a revisores" in body
    assert "não comprova" in body
    assert "Fonte selecionada para revisão" in body
    assert "Relações extraídas · confira o status" in body
    assert f'data-api-url="/api/v1/normas/{candidate.pk}/relations/?include_pending=true"' in body
    assert f'href="/normas/documentos/{document.public_id}/"' in body
    assert f'href="/normas/{candidate.pk}/"' not in body


def test_candidate_scope_lists_real_norma_with_pending_pdf_relations_without_accepting_it():
    norma = Norma.objects.create(
        tipo="Lei Complementar",
        numero="258",
        ano=2024,
        status="pending",
        identity_json={"jurisdiction": "BR-RN-NATAL"},
    )
    document = DocumentoNormativo.objects.create(
        document_key=uuid4().hex,
        norma=norma,
        source_kind=DocumentoNormativo.SourceKind.SAPL,
        source_ref=f"sapl:review-queue:{uuid4()}",
        role=DocumentoNormativo.Role.ORIGINAL,
        content_sha256="f" * 64,
        size_bytes=100,
        review_status=DocumentoNormativo.ReviewStatus.PENDING,
    )
    legal_text = (
        "Art. 260. Ficam revogados:\n"
        "VI - Lei Promulgada nº 562 de 14 de setembro de 2018.\n"
    )
    extraction = ExtracaoDocumento.objects.create(
        documento=document,
        extractor_version="candidate-explore-v1",
        policy_fingerprint="a" * 64,
        text_version="legal-text-v1",
        raw_text=legal_text,
        legal_text=legal_text,
        page_count=1,
        page_map_json=[{"start": 0, "end": len(legal_text), "page": 1}],
        status=ExtracaoDocumento.Status.COMPLETE,
        extraction_sha256="",
    )
    assert persist_document_relation_candidates(extraction)["created"] == 1

    reviewer = get_user_model().objects.create_user(
        username=f"candidate-graph-{uuid4().hex}",
        password="qa-password",
        is_staff=True,
    )
    reviewer.user_permissions.add(
        Permission.objects.get(content_type__app_label="legislation", codename="view_eventoalteracao"),
        Permission.objects.get(content_type__app_label="legislation", codename="view_documentonormativo"),
        Permission.objects.get(
            content_type__app_label="legislation",
            codename="review_eventonormativocandidato",
        ),
    )
    reviewer_client = Client()
    reviewer_client.force_login(reviewer)

    with override_settings(NORMATIVE_GRAPH_ENABLED=True):
        public = Client().get("/explorar/")
        candidates = reviewer_client.get(
            f"/explorar/?escopo=candidatas&norma={norma.pk}"
        )

    public_body = public.content.decode()
    candidate_body = candidates.content.decode()
    assert public.status_code == candidates.status_code == 200
    assert "258/2024" not in public_body
    assert "258/2024" in candidate_body
    assert "Modo restrito a revisores" in candidate_body
    assert "Relações extraídas · confira o status" in candidate_body
    assert "não comprova" in candidate_body
    assert f'data-api-url="/api/v1/normas/{norma.pk}/relations/?include_pending=true"' in candidate_body
    assert f'href="/normas/documentos/{document.public_id}/"' in candidate_body
    assert f'href="/normas/{norma.pk}/"' not in candidate_body
    assert f'href="/normas/documentos/{document.public_id}/"' not in public_body
    assert not Norma.objects.filter(pk=norma.pk, documento_base__isnull=False).exists()
    assert document.accepted_extraction_id is None


def test_candidate_scope_surfaces_unlinked_archive_pdfs_for_reviewers_only():
    document = DocumentoNormativo.objects.create(
        document_key=uuid4().hex,
        source_kind=DocumentoNormativo.SourceKind.ARCHIVE,
        source_ref=f"archive:unlinked-relation:{uuid4()}",
        role=DocumentoNormativo.Role.ORIGINAL,
        original_filename="lei-complementar-777-2024.pdf",
        content_sha256="c" * 64,
        size_bytes=100,
        review_status=DocumentoNormativo.ReviewStatus.PENDING,
        metadata_json={
            "identity_candidate": {
                "type": "Lei Complementar",
                "number": "777",
                "year": 2024,
                "jurisdiction": "BR-RN-NATAL",
            }
        },
    )
    legal_text = (
        "Art. 5º Ficam revogados:\n"
        "I - Lei Complementar nº 55 de 2004.\n"
    )
    extraction = ExtracaoDocumento.objects.create(
        documento=document,
        extractor_version="unlinked-candidate-explore-v1",
        policy_fingerprint="d" * 64,
        text_version="legal-text-v1",
        raw_text=legal_text,
        legal_text=legal_text,
        page_count=1,
        page_map_json=[{"start": 0, "end": len(legal_text), "page": 1}],
        status=ExtracaoDocumento.Status.COMPLETE,
        extraction_sha256="",
    )
    assert persist_document_relation_candidates(extraction)["created"] == 1

    reviewer = get_user_model().objects.create_user(
        username=f"unlinked-candidate-graph-{uuid4().hex}",
        password="qa-password",
        is_staff=True,
    )
    reviewer.user_permissions.add(
        Permission.objects.get(
            content_type__app_label="legislation", codename="view_eventoalteracao"
        ),
        Permission.objects.get(
            content_type__app_label="legislation", codename="view_documentonormativo"
        ),
        Permission.objects.get(
            content_type__app_label="legislation",
            codename="review_eventonormativocandidato",
        ),
    )
    reviewer_client = Client()
    reviewer_client.force_login(reviewer)

    with override_settings(NORMATIVE_GRAPH_ENABLED=True):
        public = Client().get("/explorar/?escopo=candidatas")
        candidates = reviewer_client.get("/explorar/?escopo=candidatas&q=777")

    public_body = public.content.decode()
    candidate_body = candidates.content.decode()
    assert public.status_code == 403
    assert candidates.status_code == 200
    assert candidates.context["candidate_document_count"] == 1
    assert "777/2024" in candidate_body
    assert "1 PDF com menções candidatas sem norma vinculada" in candidate_body
    assert "1 menção sem revisão" in candidate_body
    assert "Abrir menções" in candidate_body
    assert str(document.public_id) not in public_body
    assert document.norma_id is None
    assert document.accepted_extraction_id is None


def test_explore_paginates_reviewed_norm_list(norma):
    Norma.objects.bulk_create([
        Norma(tipo="Lei", numero=f"{index:04}", ano=2020, status="consolidated")
        for index in range(20)
    ])

    first = Client().get("/explorar/")
    second = Client().get("/explorar/?page=2")

    assert first.status_code == second.status_code == 200
    assert "Página 1 de 2" in first.content.decode()
    assert "Página 2 de 2" in second.content.decode()
    assert first.content.count(b"class=\"workspace-result-card explore-norm-card\"") == 20


def test_norma_list_hides_explicit_qa_only_consolidated_fixtures(norma):
    norma.numero = "9917"
    norma.ano = 2090
    norma.identity_json = {"synthetic_fixture": True}
    norma.ementa = "[QA SINTÉTICO — NÃO É LEGISLAÇÃO REAL] Fixture de coleção."
    norma.save(update_fields=["numero", "ano", "identity_json", "ementa", "updated_at"])

    body = Client().get("/normas/").content.decode()

    assert "Lei 9917/2090" not in body
    assert "[QA SINTÉTICO" not in body
    assert 'class="jurix-norma-stat-value">0<' in body


def test_workspace_norma_count_excludes_synthetic_collection_fixture(norma):
    norma.identity_json = {"synthetic_fixture": True}
    norma.save(update_fields=["identity_json", "updated_at"])

    collections_body = Client().get("/colecoes/").content.decode()
    settings_body = Client().get("/configuracoes/").content.decode()

    assert "1 normas no acervo" not in collections_body
    assert "0 consolidadas" in settings_body
    assert "PDF local" not in settings_body


def test_exact_search_does_not_surface_synthetic_consolidated_fixture(norma):
    norma.numero = "9917"
    norma.ano = 2090
    norma.identity_json = {"synthetic_fixture": True}
    norma.ementa = "[QA SINTÉTICO — NÃO É LEGISLAÇÃO REAL] Fixture de coleção."
    norma.save(update_fields=["numero", "ano", "identity_json", "ementa", "updated_at"])

    body = Client().get("/pesquisa/?q=Lei+9917%2F2090").content.decode()

    assert "Nenhum texto pesquisável localizado para esta referência" in body
    assert "A busca também não examina arquivos fora do staging." in body
    assert "[QA SINTÉTICO" not in body


def test_norma_list_surfaces_archive_candidates_only_in_qa():
    document = DocumentoNormativo.objects.create(
        document_key="a" * 64,
        source_kind=DocumentoNormativo.SourceKind.ARCHIVE,
        source_ref="archive:qa-fixture:entry:9876",
        archive_sha256="b" * 64,
        entry_index=9876,
        entry_name="sistema2/pdfs/LeiComplementar_20211220_198_.pdf",
        original_filename="LeiComplementar_20211220_198_.pdf",
        role=DocumentoNormativo.Role.ORIGINAL,
        storage_key="sha256/aa/bb/example.pdf",
        size_bytes=123,
        content_sha256="c" * 64,
        metadata_json={
            "identity_key": "BR-RN-NATAL|lei_complementar|lc|198|2021",
            "identity_candidate": {"type": "lei_complementar", "number": "198", "year": 2021},
        },
        review_status=DocumentoNormativo.ReviewStatus.PENDING,
    )
    ExtracaoDocumento.objects.create(
        documento=document,
        extractor_version="pymupdf-qa-test",
        policy_fingerprint="d" * 64,
        text_version="technical_text_v1",
        legal_text="Texto extraído para validar o estado de segmentação.",
        page_count=1,
        status=ExtracaoDocumento.Status.COMPLETE,
    )
    for index in range(40):
        DocumentoNormativo.objects.create(
            document_key=str(index + 1).zfill(64),
            source_kind=DocumentoNormativo.SourceKind.ARCHIVE,
            source_ref=f"archive:qa-fixture:entry:{10000 + index}",
            entry_index=10000 + index,
            original_filename=f"candidate-{index}.pdf",
            content_sha256=str(index + 1001).zfill(64),
            metadata_json={"identity_candidate": {"type": "lei", "number": str(index + 1), "year": 2020}},
            review_status=DocumentoNormativo.ReviewStatus.PENDING,
        )

    with override_settings(NORMATIVE_ARCHIVE_ENABLED=False):
        production_body = Client().get("/normas/").content.decode()
    assert "Documentos para consolidação" not in production_body
    with override_settings(
        DEBUG=True,
        NORMATIVE_ARCHIVE_ENABLED=True,
        NORMATIVE_ARCHIVE_REVIEW_UI_ENABLED=True,
    ):
        body = Client().get("/normas/").content.decode()
        queried_body = Client().get("/normas/", {"q": "120/2010"}).content.decode()
        typed_year_query = Client().get(
            "/normas/",
            {"q": "LC 258/2024", "tipo": "Lei Complementar", "ano": "2024"},
        ).content.decode()
        cited_question = (
            "No licenciamento urbanístico, quais normas anteriores o art. 260 da "
            "Lei Complementar nº 258/2024 expressamente revoga?"
        )
        cited_question_body = Client().get("/normas/", {"q": cited_question}).content.decode()

    assert "Documentos para consolidação" in body
    assert '<h1 id="normas-title" class="jurix-norma-title">Normas e acervo</h1>' in body
    assert "Nenhuma norma consolidada disponível" in body
    assert "Lei Complementar nº 198/2021" in body
    assert "não equivalem a redações consolidadas ou vigentes" in body
    assert "Estes documentos compõem o acervo histórico local e estão disponíveis para consulta." in body
    assert "Ainda não foram consolidados no corpus principal" in body
    assert "O Gold é um conjunto de referência para avaliação técnica, com adjudicação por IA." in body
    assert "Ele não representa revisão jurídica independente, consolidação nem confirmação de vigência." in body
    assert "Identidade candidata reconhecida; falta revisão humana." in body
    assert 'id="archive-candidate-search"' in body
    assert 'id="archive-global-search"' in body
    assert "Pesquisar em todo o acervo histórico" in body
    assert 'href="/pesquisa/?q="' in body
    assert 'href="/pesquisa/?q=120/2010"' in queried_body
    assert 'id="archive-global-search-top"' in queried_body
    assert 'href="/pesquisa/?q=120/2010"' in queried_body
    assert "A busca acima não pesquisa o texto integral destes PDFs." in queried_body
    assert (
        'href="/pesquisa/?q=Lei%20Complementar%20n%C2%BA%20258/2024&amp;arquivo_tipo=Lei%20Complementar&amp;arquivo_ano=2024"'
        in typed_year_query
    )
    top_bridge_link = cited_question_body.split('id="archive-global-search-top"', 1)[1].split(">", 1)[0]
    assert (
        'href="/pesquisa/?q=Lei%20Complementar%20n%C2%BA%20258/2024%2C%20Art.%20260"'
        in top_bridge_link
    )
    assert 'id="archive-candidate-search" type="search" autocomplete="off" spellcheck="false"' in cited_question_body
    assert 'value="Lei Complementar nº 258/2024, Art. 260"' in cited_question_body
    assert 'id="archive-candidate-identity"' in body
    assert 'id="archive-candidate-extraction"' in body
    assert 'data-identity="resolved"' in body
    assert 'data-review-status="pending"' in body
    assert 'data-extraction-status="complete"' in body
    assert "Extração completa · 1 página · segmentação de dispositivos pendente" in body
    assert "PDF candidato" in body
    assert "PDF · entrada" not in body
    assert "PDF · entrada 9876" not in body
    assert "40 exibidos · 41 no acervo" in body
    assert "Exibindo 1–40 de 41 documentos pendentes." in body
    assert 'aria-label="Paginação dos documentos candidatos"' in body
    assert "Página 1 de 2" in body
    assert "arquivo_pagina=2#archive-candidates" in body
    assert 'id="archive-candidates-list" data-total-candidates="41"' in body

    with override_settings(NORMATIVE_ARCHIVE_ENABLED=True):
        no_match = Client().get("/normas/?q=parcelamento+do+solo").content.decode()
    assert 'value="parcelamento do solo"' in no_match
    assert 'id="archive-global-search-top"' in no_match
    assert 'href="/pesquisa/?q=parcelamento%20do%20solo"' in no_match
    # This page's client-side filter covers only the first 40; keep the CTA to
    # the complete archive even when the visible subset has no matching item.
    assert 'href="/pesquisa/?q=parcelamento%20do%20solo"' in no_match
    assert (
        'class="jurix-norma-primary-button jurix-archive-global-search" id="archive-global-search"'
        in no_match
    )
    assert "Nenhuma norma consolidada corresponde aos filtros" in no_match
    assert "Não encontramos normas consolidadas para os filtros atuais." in no_match

    with override_settings(NORMATIVE_ARCHIVE_ENABLED=True):
        show_all_candidates = Client().get("/normas/").content.decode()
    assert 'id="archive-candidate-search"' in show_all_candidates
    assert 'id="archive-candidate-search" type="search" autocomplete="off" spellcheck="false"\n                    value=""' in show_all_candidates
    assert "Exibindo 1–40 de 41 documentos pendentes." in show_all_candidates

    with override_settings(NORMATIVE_ARCHIVE_ENABLED=True):
        second_candidate_page = Client().get("/normas/?arquivo_pagina=2#archive-candidates").content.decode()
    assert "Exibindo 41–41 de 41 documentos pendentes." in second_candidate_page
    assert "Página 2 de 2" in second_candidate_page
    assert "candidate-39.pdf" in second_candidate_page
    assert "Lei Complementar nº 198/2021" not in second_candidate_page
    assert "arquivo_pagina=1#archive-candidates" in second_candidate_page

    with override_settings(
        NORMATIVE_ARCHIVE_ENABLED=True,
        NORMATIVE_ARCHIVE_ASSISTANT_ENABLED=True,
    ):
        collections_body = Client().get("/colecoes/").content.decode()
        settings_body = Client().get("/configuracoes/").content.decode()

    assert "41 PDFs locais em revisão" in collections_body, [
        line.strip() for line in collections_body.splitlines() if "PDF" in line
    ]
    assert "41 PDFs locais em revisão" in settings_body
    assert "normas consolidadas" in collections_body
    assert 'href="/normas/#archive-candidates"' in settings_body
    assert "Perguntar ao assistente sobre o acervo" in collections_body


def test_natural_question_bridge_searches_archive_by_single_explicit_citation():
    DocumentoNormativo.objects.create(
        document_key="d" * 64,
        source_kind=DocumentoNormativo.SourceKind.ARCHIVE,
        source_ref="archive:qa-fixture:lc258",
        entry_index=258,
        original_filename="LeiComplementar_20241227_258_.pdf",
        metadata_json={
            "identity_key": "BR-RN-NATAL|lei_complementar|municipal_lc|258|2024",
            "identity_candidate": {
                "type": "lei_complementar",
                "number": "258",
                "year": 2024,
            },
        },
        content_sha256="e" * 64,
        review_status=DocumentoNormativo.ReviewStatus.PENDING,
    )
    question = (
        "No licenciamento urbanístico, quais normas anteriores o art. 260 da "
        "Lei Complementar nº 258/2024 expressamente revoga?"
    )

    with override_settings(
        DEBUG=True,
        NORMATIVE_ARCHIVE_ENABLED=True,
        NORMATIVE_ARCHIVE_REVIEW_UI_ENABLED=True,
        NORMATIVE_ARCHIVE_ASSISTANT_ENABLED=True,
    ):
        norms_response = Client().get("/normas/", {"q": question})
        archive_response = Client().get(
            "/pesquisa/",
            {"q": "Lei Complementar nº 258/2024, Art. 260"},
        )

    assert norms_response.status_code == 200
    norms_body = norms_response.content.decode()
    top_bridge_link = norms_body.split('id="archive-global-search-top"', 1)[1].split(">", 1)[0]
    assert (
        'href="/pesquisa/?q=Lei%20Complementar%20n%C2%BA%20258/2024%2C%20Art.%20260"'
        in top_bridge_link
    )
    assert archive_response.status_code == 200
    archive_body = archive_response.content.decode()
    assert "1 documento candidato" in archive_body
    assert "Lei Complementar nº 258/2024" in archive_body
    assert "ainda não consolidados" in archive_body


def test_norma_list_surfaces_dom_editions_only_in_qa_and_validates_official_pdf_url():
    valid_url = (
        "https://www2.natal.rn.gov.br/_anexos/publicacao/dom/"
        "dom_20261001_0123456789abcdef01234567.pdf"
    )
    DocumentoNormativo.objects.create(
        document_key="e" * 64,
        source_kind=DocumentoNormativo.SourceKind.OFFICIAL_GAZETTE,
        source_ref="dom_natal:2026:6206",
        original_filename="dom_20261001_0123456789abcdef01234567.pdf",
        role=DocumentoNormativo.Role.UNDETERMINED,
        storage_key="qa/dom/candidate.pdf",
        content_sha256="f" * 64,
        official_url=valid_url,
        metadata_json={
            "label": "DOM nº 6.206 — 1º de outubro de 2026",
            "publication_date": "2026-10-01",
            "special_edition": False,
        },
        review_status=DocumentoNormativo.ReviewStatus.PENDING,
    )

    with override_settings(NORMATIVE_ARCHIVE_ENABLED=False):
        hidden_body = Client().get("/normas/").content.decode()
    assert "Edições para revisão" not in hidden_body
    assert valid_url not in hidden_body

    with override_settings(NORMATIVE_ARCHIVE_ENABLED=True):
        body = Client().get("/normas/").content.decode()
    assert "Edições para revisão" in body
    assert "DOM nº 6.206 — 1º de outubro de 2026" in body
    assert "Publicação: 01/10/2026" in body
    assert "Extração e identificação dos atos ainda não realizadas" in body
    assert "não são normas consolidadas" in body
    assert f'href="{valid_url}"' in body
    assert "Abrir PDF oficial" in body


def test_norma_list_never_links_untrusted_dom_pdf_url():
    DocumentoNormativo.objects.create(
        document_key="d" * 64,
        source_kind=DocumentoNormativo.SourceKind.OFFICIAL_GAZETTE,
        source_ref="dom_natal:unsafe:test",
        original_filename="external.pdf",
        role=DocumentoNormativo.Role.UNDETERMINED,
        storage_key="qa/dom/external.pdf",
        content_sha256="c" * 64,
        official_url="https://example.invalid/malicious.pdf",
        metadata_json={"label": "Edição com URL inválida", "publication_date": "2026-10-01"},
        review_status=DocumentoNormativo.ReviewStatus.PENDING,
    )

    with override_settings(NORMATIVE_ARCHIVE_ENABLED=True):
        body = Client().get("/normas/").content.decode()

    assert "Edição com URL inválida" in body
    assert "Link oficial indisponível para validação." in body
    assert 'href="https://example.invalid/malicious.pdf"' not in body


def test_norma_list_rewrites_legacy_sapl_detail_url(norma):
    norma.sapl_id = 9387
    norma.sapl_url = "https://sapl.natal.rn.leg.br/norma/normajuridica/9387/"
    norma.save(update_fields=["sapl_id", "sapl_url"])
    body = Client().get("/normas/").content.decode()
    assert 'href="https://sapl.natal.rn.leg.br/norma/9387"' in body
    assert "/norma/normajuridica/9387/" not in body


def test_norma_detail_rewrites_legacy_sapl_url_without_mutating_the_record(norma):
    norma.sapl_id = 9387
    legacy = "https://sapl.natal.rn.leg.br/norma/normajuridica/9387/"
    norma.sapl_url = legacy
    norma.save(update_fields=["sapl_id", "sapl_url"])
    response = Client().get(f"/normas/{norma.pk}/")
    body = response.content.decode()
    assert response.status_code == 200
    assert 'href="https://sapl.natal.rn.leg.br/norma/9387"' in body
    assert legacy not in body
    norma.refresh_from_db()
    assert norma.sapl_url == legacy


def test_workspace_new_research_link_requests_a_blank_conversation():
    body = Client().get("/normas/").content.decode()
    assert 'href="/assistente/?new=1" id="workspace-new-chat"' in body


def test_norma_compare_renders_aligned_diff_and_explicit_missing_effective_date(norma):
    from datetime import date

    norma.data_publicacao = date(2026, 1, 1)
    norma.save(update_fields=["data_publicacao"])
    response = Client().get(f"/normas/{norma.pk}/compare/")
    body = response.content.decode()
    assert "Diferenças textuais estruturais" in body
    assert "Original (OCR)" in body
    assert "Consolidado" in body
    assert "Art. 1º Texto." in body

    detail_body = Client().get(f"/normas/{norma.pk}/").content.decode()
    assert "Não informada" in detail_body
    assert "Data de vigência não registrada no corpus" in detail_body
    assert "Confirme a vigência na fonte oficial" in detail_body


@pytest.mark.parametrize(
    "original_text",
    [
        "linha\n" * 1_000 + "linha",
        "x" * 120_001,
    ],
    ids=["line-limit", "character-limit"],
)
def test_norma_compare_declines_oversized_diff_and_links_to_full_versions(norma, original_text):
    norma.texto_original = original_text
    norma.sapl_url = "https://sapl.example.test/norma/123/"
    norma.save(update_fields=["texto_original", "sapl_url"])

    with patch("src.apps.legislation.views.build_legal_diff") as matcher:
        response = Client().get(f"/normas/{norma.pk}/compare/")

    assert response.status_code == 200
    body = response.content.decode()
    assert "Comparação grande indisponível nesta visualização" in body
    assert "Nenhum diff parcial foi gerado." in body
    assert "Ler texto consolidado completo" in body
    assert 'href="https://sapl.example.test/norma/123/"' in body
    assert "Diferenças textuais estruturais" not in body
    matcher.assert_not_called()


def test_norma_compare_unknown_norma_returns_not_found():
    response = Client().get("/normas/999999/compare/")
    assert response.status_code == 404


def test_norma_tree_exposes_hierarchy_semantics(norma):
    body = Client().get(f"/normas/{norma.pk}/tree/").content.decode()
    assert 'role="tree"' in body
    assert "Estrutura hierárquica dos dispositivos" in body


def test_norma_detail_exposes_safe_assistant_and_official_source_actions(norma):
    norma.sapl_url = "https://sapl.example.test/norma/123/"
    norma.save(update_fields=["sapl_url"])
    body = Client().get(f"/normas/{norma.pk}/").content.decode()
    assert "Perguntar sobre esta norma" in body
    assert 'href="https://sapl.example.test/norma/123/"' in body
    assert 'target="_blank"' in body
    assert 'rel="noopener noreferrer"' in body


def test_norma_detail_device_index_preserves_hierarchical_deep_links(norma):
    article = Dispositivo.objects.create(
        norma=norma, tipo="artigo", numero="1º", texto="Texto", ordem=1, caminho=""
    )
    inciso = Dispositivo.objects.create(
        norma=norma,
        tipo="inciso",
        numero="I",
        texto="Inciso",
        ordem=2,
        dispositivo_pai=article,
        caminho="",
    )
    alinea = Dispositivo.objects.create(
        norma=norma,
        tipo="alinea",
        numero="a)",
        texto="Alínea",
        ordem=3,
        dispositivo_pai=inciso,
        caminho="",
    )
    second_article = Dispositivo.objects.create(
        norma=norma, tipo="artigo", numero="2º", texto="Texto", ordem=4, caminho=""
    )

    body = Client().get(f"/normas/{norma.pk}/").content.decode()

    assert 'class="dispositivos-index-links" data-device-index' in body
    assert f'href="#dispositivo-{article.pk}"' in body
    assert f'href="#dispositivo-{inciso.pk}"' in body
    assert f'href="#dispositivo-{alinea.pk}"' in body
    assert f'href="#dispositivo-{second_article.pk}"' in body
    assert f'data-device-parent-id="{inciso.pk}"' in body
    assert 'data-device-type="artigo"' in body


def test_norma_pdf_export_returns_a_real_pdf(norma):
    import fitz

    response = Client().get(f"/normas/{norma.pk}/export/pdf/")
    assert response.status_code == 200
    assert response["Content-Type"] == "application/pdf"
    assert response["Content-Disposition"].startswith("attachment;")
    assert response.content.startswith(b"%PDF-")
    with fitz.open(stream=response.content, filetype="pdf") as document:
        exported_text = "\n".join(page.get_text() for page in document)
    assert "Art. 1º Texto." in exported_text


def test_assistant_can_prefill_a_consolidated_norm_context(norma):
    body = Client().get(f"/assistente/?norma_id={norma.pk}").content.decode()
    assert f"Sobre Lei nº {norma.numero}/{norma.ano}:" in body


def test_assistant_prefills_a_bounded_question_without_creating_a_session():
    question = "O que prevê o art. 18 da Lei Complementar nº 120/2010?"
    response = Client().get(
        "/assistente/",
        {"new": "1", "corpus": "archive-qa", "question": question},
    )

    assert response.status_code == 200
    body = response.content.decode()
    assert question in body
    assert f'value="{question}"' in body
    assert ChatSession.objects.count() == 0


def test_assistant_ignores_unknown_or_non_numeric_norm_context(norma):
    for query in ("?norma_id=not-a-number", "?norma_id=999999"):
        body = Client().get(f"/assistente/{query}").content.decode()
        assert "Sobre Lei nº" not in body


def test_norma_detail_api_returns_devices_without_model_helper_error(norma):
    response = Client().get(f"/api/v1/normas/{norma.pk}/")
    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["norma"]["id"] == norma.pk
    assert payload["dispositivos"] == []


def test_norma_detail_api_builds_missing_hierarchy_from_loaded_tree(norma):
    article = Dispositivo.objects.create(
        norma=norma, tipo="artigo", numero="1º", texto="Texto", ordem=1, caminho=""
    )
    paragraph = Dispositivo.objects.create(
        norma=norma,
        tipo="paragrafo",
        numero="2º",
        texto="Parágrafo",
        ordem=2,
        dispositivo_pai=article,
        caminho="",
    )

    payload = Client().get(f"/api/v1/normas/{norma.pk}/").json()
    by_id = {item["id"]: item for item in payload["dispositivos"]}
    assert by_id[paragraph.id]["hierarchy"] == "Art. 1º > § 2º"


def test_norma_detail_api_returns_json_404_for_unknown_norma():
    response = Client().get("/api/v1/normas/999999/")
    assert response.status_code == 404
    assert response.json() == {
        "success": False,
        "error": "Norma with ID 999999 not found",
    }


def test_first_party_templates_do_not_depend_on_inline_csp_bypasses():
    root = Path(__file__).parents[1] / "apps" / "legislation" / "templates"
    for template in root.rglob("*.html"):
        source = template.read_text(encoding="utf-8")
        assert "<style" not in source.lower(), template
        assert "style=" not in source.lower(), template
        assert "javascript:" not in source.lower(), template

    css = (
        Path(__file__).parents[1] / "apps" / "core" / "static" / "css" / "jurix-legacy-shell.css"
    ).read_text(encoding="utf-8")
    assert "@media (max-width:640px)" in css
    assert ".tree-node { margin-left:8px" in css
    assert ".compare-container { display: grid; grid-template-columns: minmax(0, 1fr)" in css
    assert ".alert-info strong { color: var(--figma-text-white); }" in css


def test_norma_api_filters_by_human_type_and_year():
    Norma.objects.create(tipo="Decreto", numero="1", ano=2025, status="consolidated")
    Norma.objects.create(tipo="Lei", numero="2", ano=2026, status="consolidated")
    response = Client().get("/api/v1/normas/?tipo=Decreto&ano=2025")
    assert response.status_code == 200
    data = response.json()["normas"]
    assert [(item["tipo"], item["ano"]) for item in data] == [("Decreto", 2025)]
    by_code = Client().get("/api/v1/normas/?tipo=3&ano=2025")
    assert [(item["tipo"], item["ano"]) for item in by_code.json()["normas"]] == [("Decreto", 2025)]

    oversized = Client().get("/api/v1/normas/?search=" + ("x" * 201))
    assert oversized.status_code == 400
    assert "Busca muito longa" in oversized.json()["error"]

    search_page = Client().get("/pesquisa/?q=" + ("x" * 201))
    assert search_page.status_code == 200
    search_body = search_page.content.decode("utf-8")
    assert "Busca muito longa" in search_body
    assert "Busca não executada" in search_body


def test_norma_api_reports_clamped_page_number():
    Norma.objects.create(tipo="Lei", numero="1", ano=2025, status="consolidated")
    response = Client().get("/api/v1/normas/?page=999&page_size=1")

    assert response.status_code == 200
    pagination = response.json()["pagination"]
    assert pagination["page"] == pagination["total_pages"] == 1


def test_legal_search_collapses_multiple_device_hits_per_norm(norma):
    other = Norma.objects.create(tipo="Lei", numero="456", ano=2025, status="consolidated")
    rows = [
        {"norma": norma, "dispositivo": SimpleNamespace(pk=1), "similarity_score": 0.91},
        {"norma": norma, "dispositivo": SimpleNamespace(pk=2), "similarity_score": 0.88},
        {"norma": other, "dispositivo": SimpleNamespace(pk=3), "similarity_score": 0.80},
    ]
    result = _deduplicate_search_results(rows)
    assert [row["norma"].pk for row in result] == [norma.pk, other.pk]
    assert result[0]["dispositivo"].pk == 1

    invalid = Client().get("/api/v1/normas/?ano=not-a-year")
    assert invalid.status_code == 400

    for page_size in ("0", "-10"):
        bounded = Client().get(f"/api/v1/normas/?page_size={page_size}")
        assert bounded.status_code == 200
        assert bounded.json()["pagination"]["page_size"] == 1


@override_settings(
    DEBUG=True,
    NORMATIVE_ARCHIVE_ENABLED=True,
    NORMATIVE_ARCHIVE_REVIEW_UI_ENABLED=True,
    NORMATIVE_ARCHIVE_ASSISTANT_ENABLED=True,
)
@patch("src.apps.legislation.workspace_views.search_archive_documents")
def test_legal_search_keeps_archive_assistant_entry_visible_with_consolidated_hits(
    search_archive, norma
):
    search_archive.return_value = {
        "results": [],
        "count": 0,
        "record_count": 0,
        "page": None,
        "expanded": False,
        "groups": (),
        "types": [],
        "years": [],
        "total_candidates": 5,
    }
    query = f"Lei nº {norma.numero}/{norma.ano}"

    response = Client().get("/pesquisa/", {"q": query})

    body = response.content.decode()
    assert response.status_code == 200
    assert "resultado consolidado" in body
    assert 'class="workspace-corpus-entry"' in body
    assert "Perguntar usando PDFs em revisão" in body
    assert "corpus=archive-qa" in body
    assert "question=Lei%20n%C2%BA%20" in body


@pytest.mark.skipif(
    connection.vendor != "sqlite",
    reason="Este caso testa o fallback lexical específico de SQLite.",
)
def test_legal_search_labels_sqlite_lexical_fallback_as_text_search(norma):
    Dispositivo.objects.create(
        norma=norma,
        tipo="artigo",
        numero="1º",
        ordem=1,
        texto="zoneamento urbano municipal",
    )

    response = Client().get("/pesquisa/", {"q": "zoneamento urbano"})

    assert response.status_code == 200
    assert b"Busca textual" in response.content


def test_legal_search_uses_retrieval_metadata_and_falls_back_after_semantic_failure(monkeypatch):
    class FakeRAG:
        def semantic_search(self, **kwargs):
            assert kwargs["include_metadata"] is True
            return {"results": [], "mode": "unavailable"}

    monkeypatch.setattr("src.apps.legislation.workspace_views.RAGService", FakeRAG)
    response = Client().get("/pesquisa/", {"q": "tema sem resultado"})

    assert response.status_code == 200
    assert b"Busca textual" in response.content
    assert (
        b"busca sem\xc3\xa2ntica est\xc3\xa1 temporariamente indispon\xc3\xadvel"
        in response.content
    )


def test_legal_search_labels_successful_vector_retrieval_as_semantic(monkeypatch):
    class FakeRAG:
        def semantic_search(self, **kwargs):
            return {"results": [], "mode": "semantic"}

    monkeypatch.setattr("src.apps.legislation.workspace_views.RAGService", FakeRAG)
    response = Client().get("/pesquisa/", {"q": "tema sem resultado"})

    assert response.status_code == 200
    assert b"Busca sem\xc3\xa2ntica" in response.content


def test_empty_search_offers_separate_review_archive_search(monkeypatch):
    document = DocumentoNormativo.objects.create(
        document_key="e" * 64,
        source_kind=DocumentoNormativo.SourceKind.ARCHIVE,
        source_ref="archive:qa-fixture:entry:4321",
        archive_sha256="f" * 64,
        entry_index=4321,
        entry_name="fixture/Lei_4321.pdf",
        original_filename="Lei_4321.pdf",
        role=DocumentoNormativo.Role.ORIGINAL,
        storage_key="sha256/ee/ff/fixture.pdf",
        size_bytes=321,
        content_sha256="a" * 64,
        review_status=DocumentoNormativo.ReviewStatus.PENDING,
    )
    ExtracaoDocumento.objects.create(
        documento=document,
        extractor_version="pymupdf-qa-test",
        policy_fingerprint="f" * 64,
        text_version="technical_text_v1",
        legal_text="O vencimento básico será calculado conforme a regra do município.",
        page_count=1,
        status=ExtracaoDocumento.Status.COMPLETE,
    )

    class FakeRAG:
        def semantic_search(self, **kwargs):
            return {"results": [], "mode": "semantic"}

    monkeypatch.setattr("src.apps.legislation.workspace_views.RAGService", FakeRAG)
    with override_settings(
        DEBUG=True,
        NORMATIVE_ARCHIVE_ENABLED=True,
        NORMATIVE_ARCHIVE_ASSISTANT_ENABLED=True,
        NORMATIVE_ARCHIVE_REVIEW_UI_ENABLED=True,
    ):
        response = Client().get("/pesquisa/", {"q": "vencimento básico"})

    body = response.content.decode()
    assert response.status_code == 200
    assert response.context[0]["archive_search_available"] is True
    assert 'class="workspace-archive-search-summary" role="status"' in body
    assert "1 PDF candidato no acervo local" in body
    assert 'href="#workspace-archive-results-title">Ver PDFs candidatos</a>' in body
    assert "PDFs locais ainda estão em revisão" in body
    assert (
        'href="/assistente/?new=1&amp;corpus=archive-qa&amp;question=vencimento%20b%C3%A1sico"'
        in body
    )
    assert 'href="/normas/#archive-candidates"' in body


def test_archive_search_shows_identity_conflict_for_pending_real_source_candidate(monkeypatch):
    document = DocumentoNormativo.objects.create(
        document_key=uuid4().hex,
        source_kind=DocumentoNormativo.SourceKind.ARCHIVE,
        source_ref="municipal_virtual_library:test-bvn-4566-1992",
        original_filename="lei_4.566.pdf",
        content_sha256="8" * 64,
        official_url="https://www2.natal.rn.gov.br/bvn/publicacoes/lei_4.566.pdf",
        review_status=DocumentoNormativo.ReviewStatus.PENDING,
        metadata_json={
            "identity_status": "conflicting_evidence",
            "identity_candidate": {"type": "lei", "number": "4566", "year": 1992},
            "identity_conflict": {
                "catalogue": "BVN classifies the record as ordinary law",
                "pdf_body": "PDF says DECRETA; Art. 2 calls it presente Decreto",
            },
            "rag_eligible": False,
        },
    )
    ExtracaoDocumento.objects.create(
        documento=document,
        extractor_version="bvn-4566-conflict-search-test",
        policy_fingerprint="9" * 64,
        text_version="legal-text-test-v1",
        legal_text="Art. 1o – Hotel-Residência.",
        page_count=2,
        status=ExtracaoDocumento.Status.COMPLETE,
    )

    class FakeRAG:
        def semantic_search(self, **kwargs):
            return {"results": [], "mode": "semantic"}

    monkeypatch.setattr("src.apps.legislation.workspace_views.RAGService", FakeRAG)
    with override_settings(
        DEBUG=True,
        NORMATIVE_ARCHIVE_ENABLED=True,
        NORMATIVE_ARCHIVE_REVIEW_UI_ENABLED=True,
    ):
        response = Client().get("/pesquisa/", {"q": "4566"})

    body = response.content.decode()
    archive_result = response.context[0]["archive_results"][0]
    assert response.status_code == 200
    assert archive_result["identity_status"] == "conflicting_evidence"
    assert archive_result["identity_conflict"]["catalogue"].startswith("BVN classifies")
    assert "Identidade: em conflito documental" in body
    assert "Identidade do ato não resolvida" in body
    assert "não é norma consolidada nem fonte elegível ao RAG" in body
    assert "lei_4.566.pdf" in body


def test_repeated_archive_excerpt_is_collapsed_without_merging_distinct_pdfs(monkeypatch):
    documents = []
    for index in (640, 641):
        document = DocumentoNormativo.objects.create(
            document_key=uuid4().hex,
            source_kind=DocumentoNormativo.SourceKind.ARCHIVE,
            source_ref=f"archive:qa-fixture:entry:{index}",
            entry_index=index,
            original_filename=f"Lei_{index}.pdf",
            content_sha256=str(index).zfill(64),
            review_status=DocumentoNormativo.ReviewStatus.PENDING,
            metadata_json={
                "identity_status": "candidate",
                "identity_candidate": {"type": "lei", "number": str(index), "year": 2024},
            },
        )
        ExtracaoDocumento.objects.create(
            documento=document,
            extractor_version=f"workspace-search-repeat-{index}",
            policy_fingerprint=str(index + 100).zfill(64),
            text_version="technical_text_v1",
            legal_text="A contribuição COSIP municipal segue esta regra pública.",
            page_count=1,
            status=ExtracaoDocumento.Status.COMPLETE,
        )
        documents.append(document)

    class FakeRAG:
        def semantic_search(self, **kwargs):
            return {"results": [], "mode": "semantic"}

    monkeypatch.setattr("src.apps.legislation.workspace_views.RAGService", FakeRAG)
    with override_settings(
        DEBUG=True,
        NORMATIVE_ARCHIVE_ENABLED=True,
        NORMATIVE_ARCHIVE_REVIEW_UI_ENABLED=True,
    ):
        response = Client().get("/pesquisa/", {"q": "contribuição COSIP municipal"})

    body = response.content.decode()
    results = response.context[0]["archive_results"]
    assert response.status_code == 200
    assert len(results) == 2
    assert {result["document"].pk for result in results} == {document.pk for document in documents}
    assert sum(bool(result["excerpt_duplicate_of"]) for result in results) == 1
    assert body.count("workspace-archive-duplicate-excerpt") == 1
    assert "documento distinto" in body
    assert "igualdade do trecho extraído não confirma identidade" in body
    assert all(f"Lei_{number}.pdf" in body for number in (640, 641))


def test_archive_search_explains_when_requested_act_species_has_no_candidate(monkeypatch):
    for index, kind in enumerate(("lei", "decreto"), start=630):
        document = DocumentoNormativo.objects.create(
            document_key=uuid4().hex,
            source_kind=DocumentoNormativo.SourceKind.ARCHIVE,
            source_ref=f"archive:qa-fixture:entry:{index}",
            entry_index=index,
            original_filename=f"{kind}_{index}.pdf",
            content_sha256=str(index).zfill(64),
            review_status=DocumentoNormativo.ReviewStatus.PENDING,
            metadata_json={
                "identity_status": "candidate",
                "identity_candidate": {"type": kind, "number": str(index), "year": 2024},
            },
        )
        ExtracaoDocumento.objects.create(
            documento=document,
            extractor_version=f"workspace-search-type-{index}",
            policy_fingerprint=str(index + 100).zfill(64),
            text_version="technical_text_v1",
            legal_text="A norma disciplina a contribuição COSIP.",
            page_count=1,
            status=ExtracaoDocumento.Status.COMPLETE,
        )

    class FakeRAG:
        def semantic_search(self, **kwargs):
            return {"results": [], "mode": "semantic"}

    monkeypatch.setattr("src.apps.legislation.workspace_views.RAGService", FakeRAG)
    with override_settings(
        DEBUG=True,
        NORMATIVE_ARCHIVE_ENABLED=True,
        NORMATIVE_ARCHIVE_REVIEW_UI_ENABLED=True,
    ):
        response = Client().get(
            "/pesquisa/",
            {"q": "Encontre a Lei Complementar que disciplina a COSIP"},
        )

    body = response.content.decode()
    assert response.status_code == 200
    assert "Não foi localizado candidato identificado como" in body
    assert "Lei Complementar" in body
    assert "Os resultados abaixo podem ser de outras espécies" in body
    assert "lei_630.pdf" in body
    assert "decreto_631.pdf" in body


def test_archive_review_search_can_browse_candidates_in_newest_identity_order(client):
    older = DocumentoNormativo.objects.create(
        document_key="1" * 64,
        source_kind=DocumentoNormativo.SourceKind.ARCHIVE,
        source_ref="archive:qa-fixture:entry:old",
        entry_index=1,
        original_filename="Lei_900_2004.pdf",
        content_sha256="2" * 64,
        review_status=DocumentoNormativo.ReviewStatus.PENDING,
        metadata_json={
            "identity_candidate": {"type": "lei", "number": "900", "year": 2004}
        },
    )
    newer = DocumentoNormativo.objects.create(
        document_key="3" * 64,
        source_kind=DocumentoNormativo.SourceKind.ARCHIVE,
        source_ref="archive:qa-fixture:entry:new",
        entry_index=2,
        original_filename="Lei_12_2025.pdf",
        content_sha256="4" * 64,
        review_status=DocumentoNormativo.ReviewStatus.PENDING,
        metadata_json={
            "identity_candidate": {"type": "lei", "number": "12", "year": 2025}
        },
    )

    with override_settings(
        DEBUG=True,
        NORMATIVE_ARCHIVE_ENABLED=True,
        NORMATIVE_ARCHIVE_REVIEW_UI_ENABLED=True,
    ):
        response = client.get("/pesquisa/", {"arquivo_recentes": "1"})

    body = response.content.decode()
    assert response.status_code == 200
    assert [row["document"].pk for row in response.context[0]["archive_results"]] == [
        newer.pk,
        older.pk,
    ]
    assert "Ver candidatos mais recentes" in body
    assert "Ordem decrescente pelo ano identificado" in body
    assert "PDFs ainda não consolidados" in body


def test_archive_candidate_hit_is_not_presented_only_as_semantic_miss(monkeypatch):
    DocumentoNormativo.objects.create(
        document_key="b" * 64,
        source_kind=DocumentoNormativo.SourceKind.ARCHIVE,
        source_ref="archive:qa-fixture:entry:2582024",
        archive_sha256="c" * 64,
        entry_index=2582024,
        entry_name="fixture/LeiComplementar_20241227_258_.pdf",
        original_filename="LeiComplementar_20241227_258_.pdf",
        role=DocumentoNormativo.Role.ORIGINAL,
        storage_key="sha256/bb/cc/candidate.pdf",
        size_bytes=321,
        content_sha256="d" * 64,
        review_status=DocumentoNormativo.ReviewStatus.PENDING,
        metadata_json={
            "identity_status": "candidate",
            "identity_candidate": {"type": "lei_complementar", "number": "258", "year": 2024},
        },
    )

    class FakeRAG:
        def semantic_search(self, **kwargs):
            return {"results": [], "mode": "semantic"}

    monkeypatch.setattr("src.apps.legislation.workspace_views.RAGService", FakeRAG)
    with override_settings(
        DEBUG=True,
        NORMATIVE_ARCHIVE_ENABLED=True,
        NORMATIVE_ARCHIVE_REVIEW_UI_ENABLED=True,
    ):
        response = Client().get("/pesquisa/", {"q": "258/2024"})

    body = response.content.decode()
    assert response.status_code == 200
    assert "0 resultados consolidados" in body
    assert "Nenhuma norma consolidada para esta consulta" in body
    assert "A busca encontrou 1 PDF candidato no acervo histórico, exibidos abaixo" in body
    assert "Nenhuma correspondência semântica encontrada" not in body
    assert "LeiComplementar_20241227_258_.pdf" in body
    assert "Eles permanecem pendentes de revisão" in body

    with override_settings(
        DEBUG=True,
        NORMATIVE_ARCHIVE_ENABLED=True,
        NORMATIVE_ARCHIVE_REVIEW_UI_ENABLED=True,
    ):
        filtered_response = Client().get(
            "/pesquisa/",
            {
                "q": "258/2024",
                "arquivo_tipo": "Lei Complementar",
                "arquivo_ano": "2024",
                "arquivo_revisao": "pending",
            },
        )
    filtered_body = filtered_response.content.decode()
    assert filtered_response.status_code == 200
    assert 'aria-label="Filtros aplicados aos PDFs locais"' in filtered_body
    assert "Espécie: Lei Complementar" in filtered_body
    assert "Ano: 2024" in filtered_body
    assert "Revisão: Pendente" in filtered_body


def test_legal_search_never_presents_synthetic_qa_norms_as_product_results(norma, monkeypatch):
    norma.identity_json = {"synthetic_fixture": True}
    norma.save(update_fields=["identity_json", "updated_at"])
    device = Dispositivo.objects.create(
        norma=norma,
        tipo="artigo",
        numero="1º",
        ordem=1,
        texto="plano de cargos sintético para QA",
    )

    class FakeRAG:
        def semantic_search(self, **kwargs):
            return {
                "results": [{"dispositivo": device, "similarity_score": 0.99, "context": {}}],
                "mode": "semantic",
            }

    monkeypatch.setattr("src.apps.legislation.workspace_views.RAGService", FakeRAG)
    response = Client().get("/pesquisa/", {"q": "plano de cargos"})

    assert response.status_code == 200
    assert b"0 resultados consolidados" in response.content
    assert f"/normas/{norma.pk}/".encode() not in response.content
    assert b"Fixture sint\xc3\xa9tica de QA" not in response.content


def test_legal_search_result_links_to_the_matching_device(norma, monkeypatch):
    device = Dispositivo.objects.create(
        norma=norma,
        tipo="artigo",
        numero="1º",
        ordem=1,
        texto="Texto específico pesquisado.",
    )

    class FakeRAG:
        def semantic_search(self, **kwargs):
            return {
                "results": [{"dispositivo": device, "similarity_score": 0.9, "context": {}}],
                "mode": "semantic",
            }

    monkeypatch.setattr("src.apps.legislation.workspace_views.RAGService", FakeRAG)
    response = Client().get("/pesquisa/", {"q": "texto específico"})
    expected_href = f"/normas/{norma.pk}/#dispositivo-{device.pk}"

    assert response.status_code == 200
    assert expected_href.encode() in response.content
    detail = Client().get(expected_href.split("#", 1)[0])
    assert f'id="dispositivo-{device.pk}"'.encode() in detail.content


def test_legal_search_resolves_explicit_norm_and_article_before_semantic_search(monkeypatch):
    target = Norma.objects.create(
        tipo="Lei",
        numero="8206",
        ano=2026,
        status="consolidated",
        ementa="Institui o Programa Municipal de Educação Popular.",
        texto_consolidado="Art. 1º Institui o programa. Art. 4º Entra em vigor na publicação.",
    )
    target_article = Dispositivo.objects.create(
        norma=target,
        tipo="artigo",
        numero="1º",
        ordem=1,
        texto="Fica instituído o Programa Municipal de Educação Popular.",
    )
    distractor = Norma.objects.create(
        tipo="Lei",
        numero="8206",
        ano=2025,
        status="consolidated",
        ementa="Cláusula genérica de vigência.",
        texto_consolidado="Art. 4º Entra em vigor na publicação.",
    )
    Dispositivo.objects.create(
        norma=distractor,
        tipo="artigo",
        numero="1º",
        ordem=1,
        texto="Artigo não relacionado à lei do pedido.",
    )

    class UnexpectedRAG:
        def semantic_search(self, **kwargs):
            raise AssertionError("Explicit norm lookup must not call semantic RAG")

    monkeypatch.setattr("src.apps.legislation.workspace_views.RAGService", UnexpectedRAG)
    client = Client()
    whole_law = client.get("/pesquisa/", {"q": "O que prevê a Lei nº 8.206/2026?"})
    article = client.get("/pesquisa/", {"q": "O que prevê o art. 1º da Lei nº 8.206/2026?"})

    assert whole_law.status_code == article.status_code == 200
    assert f"/normas/{target.pk}/".encode() in whole_law.content
    assert target.ementa.encode() in whole_law.content
    assert "Cláusula genérica de vigência".encode() not in whole_law.content
    assert f"/normas/{target.pk}/#dispositivo-{target_article.pk}".encode() in article.content
    assert f"/normas/{distractor.pk}/".encode() not in article.content


def test_legal_search_explicit_missing_norm_returns_a_qualified_empty_state(monkeypatch):
    other_year = Norma.objects.create(tipo="Lei", numero="8206", ano=2025, status="consolidated")

    class UnexpectedRAG:
        def semantic_search(self, **kwargs):
            raise AssertionError("An exact missing reference must not drift to semantic results")

    monkeypatch.setattr("src.apps.legislation.workspace_views.RAGService", UnexpectedRAG)
    response = Client().get("/pesquisa/", {"q": "O que prevê a Lei nº 8206/2026?"})

    assert response.status_code == 200
    assert response.context["exact_reference_not_found"] is True
    body = response.content.decode("utf-8").lower()
    assert "nenhum texto pesquisável localizado para esta referência" in body
    assert "isso não prova que a norma inexista" in body
    assert "consultar acervo normativo e catálogo sapl" in body
    assert f"/normas/{other_year.pk}/".encode() not in response.content
