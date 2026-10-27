"""Bounded retrieval and generation over the same immutable experimental dossier."""

from __future__ import annotations

import re
import time
from collections.abc import Callable, Iterator
from datetime import date

from src.processing.normative_query import classify_normative_query
from src.processing.normative_reference import normalize_number, parse_normative_references
from src.processing.pilot_casefile import (
    build_pilot_casefile,
    casefile_citation_sources,
    casefile_url,
    evidence_citation_source,
    norm_label,
)
from src.processing.pilot_corpus import resolve_pilot_query
from src.processing.pilot_events import device_span, evidence
from src.processing.pilot_projection import device_paths
from src.processing.qa_archive_rag import (
    _archive_search_tokens,
    _explicit_article_norm_pairs,
    _sample_whole_norm_rows,
    _tokens,
    _whole_norm_topic_tokens,
)

ARMS = {"baseline", "grafo", "grafo_temporal"}
_COMPARISON = re.compile(r"\bo que mudou\b|\bantes e depois\b|\bcompar[ae]|\brevog\w*|\bnova reda[cç][aã]o\b", re.I)
_PREVIOUS_ARTICLE = re.compile(r"\bartigo\s+anterior\b", re.I)


def _identity(key):
    _j, kind, number, year = key.split("|")
    return kind, normalize_number(number).lstrip("0") or "0", int(year)


def _article_path(value):
    # The shared classifier represents 2-A as 2a; the portable structural path
    # retains the separator, as does the source parser's identity.
    return "art:" + re.sub(r"^(\d+)([a-z]+)$", r"\1-\2", value.casefold())


def _source_row(source, path):
    span = device_span(source, path)
    if not span:
        return None
    raw = {**evidence(source, *span, label=path), "citation_index": 0}
    return {**evidence_citation_source(raw, revision="", casefile_id=""), "_path": path, "_source": source}


def retrieve_pilot_context(corpus: dict, question: str, *, previous_question: str = "",
                           as_of: date | str | None = None, arm: str = "grafo_temporal",
                           context_chars: int = 8000, k: int = 12) -> dict:
    """Resolve intent before a shortlist; never reads questions or labels from Gold.

    Baseline sees only literal indexed text. Graph adds documentary neighbours;
    graph-temporal additionally exposes the bounded projection. All arms use the
    same input inventory and context budget, reported separately from retrieval.
    """
    if arm not in ARMS:
        raise ValueError("Unknown pilot retrieval arm")
    if not 1000 <= context_chars <= 48000:
        raise ValueError("Pilot context budget must be between 1000 and 48000 characters")
    previous = resolve_pilot_query(previous_question, corpus["sources"]) if previous_question else {}
    context_keys = tuple({key for group in previous.get("references", []) if group["status"] == "resolved" for key in group["norma_keys"]})
    resolution = resolve_pilot_query(question, corpus["sources"], context_keys=context_keys)
    expanded = resolution["retrieval_question"]
    plan = classify_normative_query(expanded)
    comparison = bool(plan.relation_intent == "modification" or _COMPARISON.search(expanded))
    invalid_day = None
    day = None
    try:
        day = date.fromisoformat(as_of) if isinstance(as_of, str) else as_of
    except ValueError:
        invalid_day = as_of
    if day is None:
        explicit_day = re.search(r"\b(?:em|na data de|no dia)\s+(\d{4}-\d{2}-\d{2}|\d{2}/\d{2}/\d{4})\b", question, re.I)
        if explicit_day:
            value = explicit_day.group(1)
            try:
                day = date.fromisoformat(value if "-" in value else "-".join(reversed(value.split("/"))))
            except ValueError:
                invalid_day = value
    intent = "temporal" if day else "comparison" if comparison else plan.kind
    result = {
        "schema_version": "jurix-pilot-retrieval-v1", "corpus_revision": corpus["corpus_revision"],
        "arm": arm, "intent": intent, "as_of": day.isoformat() if day else None,
        "resolution": resolution, "norma_keys": [], "casefiles": [], "sources": [], "context_sources": [],
        "pending": [], "coverage": {"corpus": "pilot", "complete": False, "context_budget_chars": context_chars},
    }
    if invalid_day:
        result["pending"].append({"reason": "invalid_date", "value": invalid_day})
        return result
    keys = []
    for group in resolution["references"]:
        if group["status"] == "resolved":
            keys.extend(group["norma_keys"])
        else:
            result["pending"].append(group)
    result["pending"].extend(resolution["ambiguous_aliases"])
    keys = list(dict.fromkeys(keys))
    if not keys and resolution["references"]:
        return result  # No silent species/year fallback for an explicit reference.
    if not keys and len(context_keys) > 1 and (plan.article_targets or _PREVIOUS_ARTICLE.search(question)):
        result["pending"].append({"reason": "conversation_identity_ambiguous", "candidates": list(context_keys)})
        return result
    rows, total_articles, selections = [], 0, {}
    pairs = _explicit_article_norm_pairs(expanded)
    parsed = parse_normative_references(expanded)
    for key in keys:
        groups = [group for group in resolution["references"] if key in group["norma_keys"]]
        edition = next((group["requested_edition_year"] for group in groups if group["requested_edition_year"] is not None), None)
        editions = [source for source in corpus["sources"] if source["norma_key"] == key and (
            source.get("edition_year") == edition if edition is not None else source["source_role"] == "primary"
        )]
        if len(editions) != 1:
            result["pending"].append({"norma_key": key, "reason": "edition_ambiguous_or_missing"})
            continue
        source = editions[0]
        paths = [_article_path(article) for identity, article in pairs if identity == _identity(key)]
        if not paths and len(keys) == 1:
            paths = [_article_path(value) for value in plan.article_targets]
        if len(keys) > 1 and plan.article_targets and not paths:
            result["pending"].append({"norma_key": key, "reason": "article_norm_pair_unresolved"})
            continue
        if not paths and _PREVIOUS_ARTICLE.search(question) and len(context_keys) == 1:
            earlier = classify_normative_query(previous["retrieval_question"]).article_targets
            articles = [path for path in device_paths(source) if "/" not in path]
            previous_path = _article_path(earlier[-1]) if earlier else None
            if previous_path in articles and articles.index(previous_path) > 0:
                paths = [articles[articles.index(previous_path) - 1]]
            else:
                result["pending"].append({"norma_key": key, "reason": "previous_article_unresolved"})
                continue
        if not paths and comparison and context_keys == (key,):
            paths = [_article_path(value) for value in classify_normative_query(previous.get("retrieval_question", "")).article_targets]
        if len(paths) == 1 and len(parsed) == 1 and parsed[0].paragraph:
            paths[0] += f"/par:{parsed[0].paragraph.casefold().replace('único', 'unico')}"
        if len(paths) == 1 and len(parsed) == 1 and parsed[0].item:
            paths[0] += f"/inc:{parsed[0].item.casefold()}"
        if paths:
            selected = []
            for path in dict.fromkeys(paths):
                row = _source_row(source, path)
                if row:
                    selected.append(row)
                else:
                    result["pending"].append({"norma_key": key, "device_path": path, "reason": "device_missing_or_ambiguous"})
            if not selected:
                continue
            rows.extend(selected)
            total_articles += len(paths)
        else:
            if comparison:
                related = build_pilot_casefile(corpus, key, source_sha256=source["pdf_sha256"])
                available = [item["device_path"] for item in related["devices"]]
            else:
                available = [path for path in device_paths(source) if "/" not in path]
            candidates = [row for path in available if (row := _source_row(source, path))]
            total_articles += len(candidates)
            selected, _total = _sample_whole_norm_rows(candidates, topic_tokens=_whole_norm_topic_tokens(expanded) if plan.broad_topical_scope else None, budget_chars=context_chars)
            rows.extend(selected)
        selections[key] = source
    if not keys and not result["pending"]:
        # Reuse archive token normalization, but restrict the population to this
        # exact manifest. Lexical ranking is not calibrated legal confidence.
        terms = _archive_search_tokens(_tokens(question))
        ranked = []
        for source in corpus["sources"]:
            if source["source_role"] != "primary":
                continue
            for path in device_paths(source):
                if "/" in path:
                    continue
                row = _source_row(source, path)
                overlap = terms & _tokens(row["full_text"]) if row else set()
                if overlap:
                    ranked.append((len(overlap) / max(1, len(terms)), source["norma_key"], path, row))
        ranked.sort(key=lambda item: (-item[0], item[1], item[2]))
        rows = [item[3] for item in ranked[:max(1, min(k, 40))]]
        total_articles = len(ranked)
        for row in rows:
            selections[row["norma_key"]] = row["_source"]
    result["norma_keys"] = list(selections)
    by_citation = {}
    for key, source in selections.items():
        selected_paths = tuple(dict.fromkeys(row["_path"] for row in rows if row["norma_key"] == key))
        # The dossier serves the selected scope, not a different default card.
        casefile = build_pilot_casefile(corpus, key, paths=selected_paths[:40], as_of=day if arm == "grafo_temporal" else None, source_sha256=source["pdf_sha256"])
        result["casefiles"].append(casefile)
        href = casefile_url(key, corpus["corpus_revision"], dispositivo=selected_paths[:40], edicao=source["pdf_sha256"], as_of=casefile["as_of"])
        for row in rows:
            if row["norma_key"] == key:
                by_citation[row["citation_id"]] = {**{name: value for name, value in row.items() if not name.startswith("_")}, "casefile_id": casefile["casefile_id"], "casefile_url": href, "corpus_revision": corpus["corpus_revision"]}
        if arm != "baseline":
            for row in casefile_citation_sources(casefile):
                by_citation.setdefault(row["citation_id"], {**row, "casefile_url": href})
    sources = list(by_citation.values())
    used, consumed = [], 0
    for index, row in enumerate(sources, 1):
        row["citation_index"] = index
        # Source links, hashes and full excerpts remain available even when an
        # intact operative clause does not fit in the model's context.
        size = len(row["full_text"])
        if consumed + size <= context_chars:
            used.append(row)
            consumed += size
    result.update(sources=sources, context_sources=used)
    result["coverage"].update({
        "complete": len(used) == len(sources) and not result["pending"] and len(rows) == total_articles,
        "retrieved_devices": total_articles, "selected_devices": len(rows), "retrieved_sources": len(sources),
        "context_sources": len(used), "context_chars": consumed,
        "omitted_citation_ids": [row["citation_id"] for row in sources if row not in used],
        "whole_norm_requested": plan.is_norma_overview, "source_population": len(corpus["sources"]),
    })
    return result


def _markers(rows: list[dict], items: list[dict | None]) -> str:
    identities = {item["citation_id"] for item in items if item}
    return " ".join(f"[[{row['citation_index']}]]" for row in rows if row["citation_id"] in identities)


def _documentary_conclusion(retrieval: dict) -> str:
    """Material action/target/date claims come from the dossier, not model prose."""
    if retrieval["arm"] != "grafo_temporal" or retrieval["intent"] not in {"comparison", "temporal"}:
        return ""
    parts = []
    for casefile in retrieval["casefiles"]:
        for device in casefile["devices"]:
            label = f"{device['label']} da {casefile['label']}"
            related = device["events"]
            applied = [event for event in related if event["event_id"] in device["applied_events"]]
            marks = _markers(retrieval["sources"], [device["base_evidence"], *(event["evidence"] for event in related)])
            if device["status"] == "conflict":
                parts.append(f"Há conflito documental em **{label}**. As fontes não permitem escolher uma redação única no escopo processado. {marks}")
            elif device["status"] == "out_of_coverage":
                parts.append(f"A edição disponível de **{label}** não permite reconstruir a data pedida. A comparação não substituiu essa lacuna por uma redação atual. {marks}")
            elif device["status"] == "unknown_date":
                modifiers = ", ".join(dict.fromkeys(norm_label(event["source_norma_key"]) for event in related))
                parts.append(f"Localizei alteração documental de **{label}** por {modifiers or 'ato modificador'}, mas a data de início não está comprovada. O cotejo não atribui vigência à redação em uma data. {marks}")
            elif device["legal_status"] == "revoked_in_scope":
                by = ", ".join(dict.fromkeys(norm_label(event["source_norma_key"]) for event in applied))
                dates = _markers(retrieval["sources"], [item for event in applied for field in ("publication_evidence", "commencement_evidence") for item in event["temporal"].get(field, [])])
                when = f", a partir de **{device['interval']['start']}**, pela derivação experimental da publicação e da cláusula de início" if device["interval"]["start"] else ""
                parts.append(f"**{label} está revogado no escopo reconstruído**, por {by}{when}. O texto histórico permanece disponível na ficha. {marks} {dates}")
            elif device["legal_status"] in {"changed_in_scope", "partially_revoked_in_scope"}:
                by = ", ".join(dict.fromkeys(norm_label(event["source_norma_key"]) for event in applied))
                parts.append(f"Há {'revogação parcial' if device['legal_status'] == 'partially_revoked_in_scope' else 'redação alterada recuperada'} para **{label}**, por {by}, dentro das relações processadas. {marks}")
            elif device["status"] == "partial":
                parts.append(f"A comparação de **{label}** é parcial; há evento ou limite de edição que impede atribuir uma redação definitiva. {marks}")
            elif not related and not any(event["source_norma_key"] == casefile["norma_key"] for event in casefile["events"]):
                parts.append(f"Não foi localizada alteração de **{label}** entre as relações processadas. Isso não certifica ausência de alterações no universo legislativo. {marks}")
            elif retrieval["as_of"]:
                parts.append(f"Em **{retrieval['as_of']}**, o escopo reconstruído preserva a redação documental de **{label}**; o evento posterior ainda não foi aplicado. {marks}")
            for note in device["notes"]:
                if note not in parts:
                    parts.append(note)
        # An amending act may have outgoing relations but no incoming change to
        # its own article. Preserve explicit partial/total targets in the answer.
        for event in casefile["events"]:
            if event["source_norma_key"] != casefile["norma_key"]:
                continue
            marks = _markers(retrieval["sources"], [event["evidence"]])
            if event["target_norma_key"] is None:
                parts.append(f"A referência literal “{' '.join(event['evidence']['quote'].split())}” permanece com alvo não resolvido. {marks}")
            else:
                from src.processing.pilot_casefile import device_label
                target = norm_label(event["target_norma_key"])
                scope = f"somente {device_label(event['target_device_path'])}" if event["target_device_path"] else "a norma inteira identificada"
                action = {"REVOGA": "revogação", "ALTERA": "alteração", "SUBSTITUI": "substituição", "ADICIONA": "acréscimo"}.get(event["action"], "relação")
                parts.append(f"O Art. {event['source_article']} declara {action} de {target}, atingindo **{scope}** no vínculo documentado. {marks}")
    return "\n\n".join(dict.fromkeys(part.strip() for part in parts if part.strip()))


def _documentary_excerpt(retrieval: dict) -> str:
    rows = retrieval["context_sources"] or retrieval["sources"][:1]
    if not rows:
        count = retrieval["coverage"].get("source_population", "a coleção")
        if retrieval["pending"]:
            return (
                f"Esta consulta foi feita no corpus experimental ({count} PDFs). "
                "A referência ou o dispositivo solicitado não pôde ser resolvido nessa coleção. "
                "Confira a espécie, o número, o ano e a edição; isso não demonstra que a norma ou o artigo inexista."
            )
        return "Não localizei evidência textual suficiente nesta coleção experimental. A busca não comprova inexistência de legislação sobre o assunto."
    snippets = [f"{row['citation_label']}:\n\n> " + row["full_text"].strip().replace("\n", "\n> ") + f" [[{row['citation_index']}]]" for row in rows[:2]]
    return "\n\n".join(snippets)


def stream_pilot_answer(corpus: dict, question: str, *, previous_question: str = "", as_of=None,
                        arm: str = "grafo_temporal", k: int = 12, context_chars: int = 8000,
                        model: str = "llama3", temperature: float = 0.1, text_provider=None,
                        ollama=None, should_cancel: Callable[[], bool] | None = None,
                        validate_attempt=None) -> Iterator[dict]:
    """Publish sources first, then validated prose and an immutable dossier binding."""
    from src.processing.rag_answer_pipeline import (
        GenerationCancelled,
        raise_if_cancelled,
        stream_grounded_generation,
        stream_model_attempt,
    )
    from src.processing.rag_generation import validate_generated_answer
    from src.processing.rag_prompt import build_prompt

    started = time.perf_counter()
    raise_if_cancelled(should_cancel)
    yield {"event": "status", "status": "retrieving"}
    retrieval = retrieve_pilot_context(corpus, question, previous_question=previous_question, as_of=as_of, arm=arm, context_chars=context_chars, k=k)
    retrieval_ms = round((time.perf_counter() - started) * 1000)
    binding = {
        "basis": "ai_pilot", "corpus_revision": corpus["corpus_revision"], "retrieval_arm": arm,
        "casefile_ids": [item["casefile_id"] for item in retrieval["casefiles"]],
        "casefile_links": [casefile_url(item["norma_key"], corpus["corpus_revision"], dispositivo=[device["device_path"] for device in item["devices"]], edicao=item["edition_sha256"], as_of=item["as_of"]) for item in retrieval["casefiles"]],
        "norma_keys": retrieval["norma_keys"], "coverage": retrieval["coverage"], "intent": retrieval["intent"],
        "prompt_version": "jurix-pilot-rag-v1",
    }
    if len(retrieval["norma_keys"]) == 1 and retrieval["casefiles"]:
        from src.processing.pilot_casefile import device_label
        primary = retrieval["casefiles"][0]
        paths = [device["device_path"] for device in primary["devices"]]
        binding["context_question"] = primary["label"] + (", " + device_label(paths[0]) if len(paths) == 1 else "")
    binding["casefile_id"] = binding["casefile_ids"][0] if binding["casefile_ids"] else None
    # Do not deliver baseline projection fields to its generator or outward DTO.
    if arm == "grafo_temporal":
        binding["projections"] = [{"casefile_id": item["casefile_id"], "devices": [{key: device[key] for key in ("device_path", "projection_id", "status", "legal_status", "interval", "conflicts", "applied_events", "pending_events")} for device in item["devices"]]} for item in retrieval["casefiles"]]
    yield {"event": "sources", "sources": retrieval["sources"], "confidence": None,
           "retrieval_strategy": "pilot_" + arm, "coverage": retrieval["coverage"], "pilot": binding}
    raise_if_cancelled(should_cancel)
    lead = _documentary_conclusion(retrieval)
    if lead:
        yield {"event": "chunk", "chunk": lead + "\n\n", "provisional": False}
    generated, generation, fallback = "", {}, None
    if retrieval["context_sources"]:
        context = "\n\n".join(f"[[{row['citation_index']}]] {row['citation_label']}\n{row['full_text']}" for row in retrieval["context_sources"])
        prompt = build_prompt(context, question)
        prompt += (
            "\n\nESCOPO DO PILOTO: documentos experimentais, não revisão jurídica independente. "
            "Escreva até 180 palavras em um ou dois parágrafos, conclusão primeiro. "
            "Não declare vigência universal, não complete uma numeração ambígua nem infira datas. "
            "A aplicação informa ações, datas e limites separadamente; explique somente o conteúdo textual sustentado pelos excertos."
        )
        if lead:
            prompt += "\nA comparação e seus limites já foram apresentados. Não os repita; acrescente somente explicação textual curta, sem novas afirmações sobre início de efeitos ou situação vigente."
        if retrieval["coverage"]["whole_norm_requested"] and not retrieval["coverage"]["complete"]:
            prompt += "\nA evidência é uma amostra de norma extensa: não a descreva como leitura integral."
        base_validator = validate_attempt or validate_generated_answer
        def validator(text, rows):
            report = base_validator(text, rows)
            unsafe = bool(re.search(r"https?://|<\s*(?:a|script|iframe|img)\b|\]\s*\(", text, re.I))
            unresolved = arm == "grafo_temporal" and any(device["status"] in {"conflict", "unknown_date", "out_of_coverage"} for item in retrieval["casefiles"] for device in item["devices"])
            overclaim = unresolved and bool(re.search(r"\b(?:reda[cç][aã]o\s+(?:vigente|atual)|vig[eê]ncia\s+confirmada|sem\s+conflito)\b", text, re.I))
            if unsafe or overclaim:
                return {**report, "grounded": False, "source_only": False}
            return report
        yield {"event": "status", "status": "generating"}
        events = stream_grounded_generation(
            prompt,
            stream_attempt=lambda text: stream_model_attempt(text, ollama=ollama, model=model, temperature=temperature,
                                                          text_provider=text_provider, should_cancel=should_cancel, max_tokens=512),
            validate_attempt=lambda text: validator(text, retrieval["sources"]),
            should_cancel=should_cancel,
        )
        try:
            while True:
                try:
                    event = next(events)
                except StopIteration as completed:
                    generation = completed.value or {}
                    break
                if event.get("event") == "chunk":
                    generated += event.get("chunk", "")
                    yield event
        except GenerationCancelled:
            raise
        except Exception:
            fallback = "provider_unavailable"
        finally:
            events.close()
        if not generated:
            fallback = fallback or "grounding_rejected"
    else:
        fallback = "context_budget" if retrieval["sources"] else "reference_unresolved"
    answer = lead + ("\n\n" if lead else "") + generated
    if not generated:
        text = "**Modo documental — transcrição das fontes, sem síntese do modelo.**\n\n" + _documentary_excerpt(retrieval)
        answer += text
        yield {"event": "chunk", "chunk": text, "provisional": False}
    if retrieval["coverage"]["whole_norm_requested"]:
        scope = retrieval["coverage"]
        note = f"\n\nCobertura: {scope['selected_devices']} de {scope['retrieved_devices']} dispositivos selecionados da edição pesquisada; {scope['context_sources']} evidências entraram no contexto do modelo. Os demais dispositivos e os anexos devem ser conferidos na ficha/PDF."
        answer += note
        yield {"event": "chunk", "chunk": note, "provisional": False}
    binding.update({"generation_mode": "llm" if generated else "documentary", "llm_succeeded": bool(generated),
                    "fallback_reason": fallback, "context_citation_ids": [row["citation_id"] for row in retrieval["context_sources"]]})
    raise_if_cancelled(should_cancel)
    yield {"event": "done", "answer": answer.strip(), "sources": retrieval["sources"],
           "grounded": bool(retrieval["sources"]), "grounding": generation.get("grounding", {}),
           "reason_code": None if retrieval["sources"] else "pilot_reference_unresolved", "pilot": binding,
           "timings_ms": {"retrieval": retrieval_ms, "total_before_done": round((time.perf_counter() - started) * 1000)},
           "generation_attempts": generation.get("generation_attempts", []), "cached": False}
