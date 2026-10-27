"""Build a scoped AI reference set from reviewed selections, never from RAG predictions."""

from __future__ import annotations

import argparse
import hashlib
import json
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path


def digest(data):
    return hashlib.sha256(data).hexdigest()


def write_jsonl(path, rows):
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
        newline="\n",
    )


def locate(text, span):
    if "range" in span:
        start, end = span["range"]
    else:
        start = text.index(span["from"], span.get("min_offset", 0))
        end = text.index(span["until"], start + len(span["from"]))
    assert 0 <= start < end <= len(text), span
    return start, end


def excerpt(text, spans):
    ranges = sorted(locate(text, span) for span in spans)
    covers = []
    for start, end in ranges:
        if covers and start <= covers[-1][1]:
            covers[-1][1] = max(covers[-1][1], end)
        else:
            covers.append([start, end])
    pieces, mapping, cursor = [], [], 0
    for start, end in covers:
        if pieces:
            pieces.append("\n\n")
            cursor += 2
        pieces.append(text[start:end])
        mapping.append(
            {
                "source_start": start,
                "source_end": end,
                "excerpt_start": cursor,
                "excerpt_end": cursor + end - start,
            }
        )
        cursor += end - start
    return "".join(pieces), mapping


def translate(start, end, mapping):
    for segment in mapping:
        if segment["source_start"] <= start < end <= segment["source_end"]:
            offset = segment["excerpt_start"] - segment["source_start"]
            return start + offset, end + offset
    raise ValueError(f"Quote outside selected scope: {start}:{end}")


EVENTS = {
    "A-271-1-CTM20": ("n02", "art:1", "n01", "art:20", "resolved"),
    "B-258-260-I": ("n03", "art:260", None, None, "unresolved"),
    "B-258-260-II": ("n03", "art:260", None, None, "unresolved"),
    "B-258-260-III": ("n03", "art:260", "n09", "*", "resolved"),
    "B-258-260-IV": ("n03", "art:260", "n04", "*", "resolved"),
    "B-258-260-V": ("n03", "art:260", "n10", "art:21", "resolved"),
    "B-258-260-VI": ("n03", "art:260", "n11", "*", "resolved"),
    "B-258-260-VII": ("n03", "art:260", None, None, "unresolved"),
    "C-173-2-LC55-par3": ("n05", "art:2", "n04", "art:34.par:3", "resolved"),
    "C-173-2-LC55-par4": ("n05", "art:2", "n04", "art:34.par:4", "resolved"),
    "C-185-87-LC55-par3": ("n06", "art:87", "n04", "art:34.par:3", "pending_review"),
    "D-261-118-LC208-par2": ("n08", "art:118", "n07", "art:18.par:2", "resolved"),
}


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument("--inputs", type=Path, required=True)
    parser.add_argument("--curation", type=Path, required=True)
    parser.add_argument("--prior-draft", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise SystemExit("Refusing to overwrite a frozen release")
    inputs = json.loads((args.inputs / "inputs.json").read_text(encoding="utf-8"))
    curation = json.loads(args.curation.read_text(encoding="utf-8"))
    decisions = {row["unit_id"]: row for row in curation["units"]}
    assert len(decisions) == len(inputs) == 20
    now = datetime.now(UTC).isoformat()
    rows, annotations, adjudications, origins, cases, checks = [], [], [], [], [], []
    texts, maps, source_texts, norms = {}, {}, {}, {}
    for unit in inputs:
        uid = unit["unit_id"]
        spec = decisions[uid]
        raw = (args.inputs / unit["text_path"]).read_text(encoding="utf-8")
        assert digest(raw.encode()) == unit["text_sha256"]
        assert digest(Path(unit["pdf_path"]).read_bytes()) == unit["pdf_sha256"]
        selected, mapping = excerpt(raw, spec["spans"])
        texts[uid], maps[uid], source_texts[uid] = selected, mapping, raw
        norm_key = f"BR-RN-NATAL|{unit['type']}|{unit['number']}|{unit['year']}"
        norms[uid] = norm_key
        doc_key = "sha256:" + unit["pdf_sha256"]
        edition_role = "original" if unit["edition"] == "diario" else "indeterminado"
        rows.append(
            {
                "schema_version": 2,
                "norma_key": norm_key,
                "document_key": doc_key,
                "sapl_id": None,
                "norma": {
                    "tipo": unit["type"],
                    "numero": unit["number"],
                    "ano": unit["year"],
                    "jurisdicao": "BR-RN-NATAL",
                },
                "document": {
                    "source_kind": "official_gazette" if unit["edition"] == "diario" else "archive",
                    "source_ref": (
                        unit.get("official_url")
                        if unit["edition"] == "diario"
                        else f"frozen-pdf/{unit['pdf_sha256']}.pdf"
                    ),
                    "sha256": unit["pdf_sha256"],
                    "official_url": unit.get("official_url"),
                    "role": edition_role,
                    "pdf_path": None,
                },
                "text": {
                    "path": f"texts/{uid}.txt",
                    "sha256": digest(selected.encode()),
                    "text_version": "jurix-reviewed-excerpt-v1",
                    "extractor_version": "exact-source-slice-v1/" + unit["extractor_version"],
                    "ocr_status": "mixed_unreviewed",
                },
                "provenance": {
                    "retrieved_at": unit["captured_at"],
                    "selection_rationale": spec["decision"],
                },
                "condition_of_use": "unknown",
                "pilot": "technical_pilot",
                "human_review": {
                    "status": "not_reviewed",
                    "reviewer_id": None,
                    "reviewed_at": None,
                    "review_kind": "human",
                },
            }
        )
        spans = []
        for span in spec["spans"]:
            start, end = locate(raw, span)
            left, right = translate(start, end, mapping)
            spans.append(
                {
                    "span_id": f"{uid}:{span['key']}",
                    "device_key": span["key"],
                    "parent_device_key": None,
                    "label": "artigo",
                    "start": left,
                    "end": right,
                    "quote": selected[left:right],
                }
            )
        annotations.append(
            {
                "schema_version": 2,
                "annotation_id": f"ai-reference:{uid}:v1",
                "norma_key": norm_key,
                "document_key": doc_key,
                "revision": {
                    "source_text_sha256": digest(selected.encode()),
                    "text_version": rows[-1]["text"]["text_version"],
                    "extractor_version": rows[-1]["text"]["extractor_version"],
                },
                "scope": {"kind": "device", "jurisdiction": "BR-RN-NATAL", "as_of": None},
                "annotator_id": "ai:codex-session-20261018",
                "review": {
                    "status": "pending",
                    "reviewer_id": None,
                    "reviewed_at": None,
                    "review_kind": "human",
                },
                "spans": spans,
                "events": [],
            }
        )
        origins.append(
            {
                "unit_id": uid,
                "norma_key": norm_key,
                "document_key": doc_key,
                "origin_text_sha256": unit["text_sha256"],
                "origin_text_version": unit["text_version"],
                "origin_extractor_version": unit["extractor_version"],
                "excerpt_mapping": mapping,
                "reviewed_devices": [
                    {
                        "device_key": s["key"],
                        "pages": s["pages"],
                        "extent": s.get("extent", "device_text"),
                    }
                    for s in spec["spans"]
                ],
                "edition": unit["edition"],
                "qa_document_id": unit.get("document_public_id"),
                "whole_norm_reviewed": False,
                "events_exhaustive": False,
            }
        )
        identity_start = spec.get("identity_offset", 0)
        identity_end = min(identity_start + 350, len(raw))
        origins[-1]["identity_evidence"] = {
            "start": identity_start,
            "end": identity_end,
            "quote": raw[identity_start:identity_end],
            "origin_text_sha256": unit["text_sha256"],
        }
        if uid == "n11":
            ementa_end = raw.index("O PRESIDENTE")
            origins[-1]["ementa_conflict_evidence"] = {
                "start": 0,
                "end": ementa_end,
                "quote": raw[:ementa_end],
                "origin_text_sha256": unit["text_sha256"],
                "decision": "Ementa: mais de três; Art. 2º: 02 ou mais. Preservar ambos.",
            }
        adjudications.append(
            {
                "decision_id": f"ADJ-{uid}-v1",
                "unit_id": uid,
                "norma_key": norm_key,
                "status": "adjudicated_by_ai",
                "review_kind": "ai",
                "reviewer_id": curation["reviewer_id"],
                "adjudicated_at": now,
                "independent_review": False,
                "human_approved": False,
                "decision": spec["decision"],
                "supporting_span_ids": [s["span_id"] for s in spans],
                "source_text_sha256": digest(selected.encode()),
                "global_current_validity": "not_determined",
            }
        )
        checks.append(
            {
                "unit_id": uid,
                "pdf_sha256": unit["pdf_sha256"],
                "pdf_hash_verified": True,
                "origin_text_hash_verified": True,
                "pdf_path_distributed": False,
            }
        )

    by_id = {row["annotation_id"].split(":")[1]: row for row in annotations}
    draft = json.loads(args.prior_draft.read_text(encoding="utf-8"))
    propositions = []
    for event in draft["events"]:
        key = event["relation_key"]
        if key not in EVENTS:
            continue
        uid, span_key, target, target_device, resolution = EVENTS[key]
        evidence = event["evidence"]
        assert source_texts[uid][evidence["start"] : evidence["end"]] == evidence["quote"]
        left, right = translate(evidence["start"], evidence["end"], maps[uid])
        final = {
            "event_id": key,
            "action": event["action"],
            "source_span_id": f"{uid}:{span_key}",
            "target_norma_key": norms.get(target),
            "target_device_key": target_device,
            "scope": event["scope"],
            "revision": by_id[uid]["revision"]["text_version"],
            "effective_date": {
                "value": None,
                "status": "unknown",
                "basis": "Cláusula documental; aplicação temporal não reconstruída integralmente.",
            },
            "resolution": resolution,
            "evidence": {
                "quote": texts[uid][left:right],
                "start": left,
                "end": right,
                "source_text_sha256": digest(texts[uid].encode()),
            },
        }
        by_id[uid]["events"].append(final)
        propositions.append(
            {
                "candidate_id": key,
                "source": "prior_ai_documentary_draft",
                "prior_target_resolution": event["target_resolution"],
                "final_resolution": resolution,
                "target_claim": event["target"],
                "decision": event["documentary_assessment"],
                "review_kind": "ai",
                "independent_review": False,
            }
        )
    ppa_span = by_id["n16"]["spans"][0]
    for spec in curation["units"]:
        if spec.get("rejected_candidate"):
            uid = spec["unit_id"]
            propositions.append(
                {
                    "candidate_id": f"curation-recheck:{uid}",
                    "source": "same_ai_session_preliminary_curation",
                    "rejected_claim": spec["rejected_candidate"],
                    "final_resolution": "rejected_in_source_recheck",
                    "decision": spec["decision"],
                    "source_quote": by_id[uid]["spans"][0]["quote"],
                    "source_text_sha256": by_id[uid]["revision"]["source_text_sha256"],
                    "review_kind": "ai",
                    "independent_review": False,
                }
            )
    by_id["n16"]["events"].append(
        {
            "event_id": "PPA-7807-7280-anexoI",
            "action": "ALTERA",
            "source_span_id": ppa_span["span_id"],
            "target_norma_key": norms["n20"],
            "target_device_key": "anexo:I.partial",
            "scope": "Revisão parcial do Anexo I; valores e tabelas não adjudicados.",
            "revision": by_id["n16"]["revision"]["text_version"],
            "effective_date": {
                "value": None,
                "status": "unknown",
                "basis": "Art. 2º vincula vigência à publicação; tabela não reconstruída.",
            },
            "resolution": "resolved",
            "evidence": {
                "quote": ppa_span["quote"],
                "start": ppa_span["start"],
                "end": ppa_span["end"],
                "source_text_sha256": digest(texts["n16"].encode()),
            },
        }
    )

    split_by_chain = {"ctm": "development", "urbanismo": "test", "ppa": "validation"}
    assignment = {}
    for unit in inputs:
        chain = unit["chain"]
        split = split_by_chain.get(
            chain, ["development", "validation", "test"][int(digest(chain.encode())[:8], 16) % 3]
        )
        assignment[unit["unit_id"]] = {
            "norma_key": norms[unit["unit_id"]],
            "chain_key": chain,
            "split": split,
        }
    for spec in curation["units"]:
        uid = spec["unit_id"]
        supporting = spec.get("support", [uid])
        cases.append(
            {
                "case_id": f"AI-PGM-{uid}-v1",
                "query": spec["query"],
                "expected_unit_ids": supporting,
                "expected_norma_keys": [norms[s] for s in supporting],
                "expected_citation_ids": [
                    span["span_id"] for s in supporting for span in by_id[s]["spans"]
                ],
                "expected_source_ids": [by_id[s]["document_key"] for s in supporting],
                "expected_versions": {
                    by_id[s]["document_key"]: digest(texts[s].encode()) for s in supporting
                },
                "expected_abstain": spec.get("abstain", False),
                "expected_answer_points": spec["answer"],
                "relation_chain_keys": sorted({assignment[s]["chain_key"] for s in supporting}),
                "human_evidence_review": False,
                "review_kind": "ai",
                "split": assignment[uid]["split"],
                "as_of": "2026-10-18",
            }
        )
    negatives = [
        (
            "current-all",
            ["n01", "n02"],
            "Qual é a redação seguramente vigente hoje do CTM inteiro?",
            True,
            "Não há varredura completa de atos posteriores; abster-se de certificar redação integral atual.",
        ),
        (
            "paragraph-conflict",
            ["n04", "n05", "n06"],
            "Renumere automaticamente o § 3º da LC 55 para § 5º e informe uma redação definitiva.",
            True,
            "Não renumerar; divergência entre o ato e a compilação persiste.",
        ),
        (
            "partial-repeal",
            ["n03", "n10"],
            "Toda a LP 275/2009 foi revogada pelo inciso V?",
            False,
            "Não, somente Art. 21 é nomeado na cláusula.",
        ),
        (
            "generic-repeal",
            ["n14"],
            "Que lei específica o Art. 6º da Lei 7805/2025 revoga?",
            True,
            "Revogadas disposições em contrário não identifica lei-alvo; não inventar alvo nem revogação tácita.",
        ),
        (
            "regulation-vacancy",
            ["n18"],
            "A Lei 7810/2025 só entra em vigor 90 dias depois?",
            False,
            "90 dias são prazo de regulamentação; vigência na publicação pelo Art. 3º.",
        ),
        (
            "ppa-table",
            ["n16", "n20"],
            "Qual o valor consolidado de todas as metas alteradas do PPA pela Lei 7807?",
            True,
            "Tabelas e valores não foram adjudicados neste conjunto.",
        ),
        (
            "vetoed-device",
            ["n20"],
            "Quais obrigações operativas impõe o Art. 16 da Lei 7280/2021?",
            True,
            "O dispositivo e seus parágrafos aparecem como VETADO nesta publicação.",
        ),
        (
            "filename-publication",
            ["n19"],
            "O filename com 20250116 prova publicação da Lei 7811 em 16 de janeiro?",
            True,
            "Não; epígrafe de 15/01 e filename não prova publicação.",
        ),
    ]
    for suffix, units, query, abstain, answer in negatives:
        cases.append(
            {
                "case_id": f"AI-PGM-negative-{suffix}",
                "query": query,
                "expected_unit_ids": units,
                "expected_norma_keys": [norms[s] for s in units],
                "expected_citation_ids": [
                    span["span_id"] for s in units for span in by_id[s]["spans"]
                ],
                "expected_source_ids": [by_id[s]["document_key"] for s in units],
                "expected_versions": {
                    by_id[s]["document_key"]: digest(texts[s].encode()) for s in units
                },
                "expected_abstain": abstain,
                "expected_answer_points": answer,
                "relation_chain_keys": sorted({assignment[s]["chain_key"] for s in units}),
                "human_evidence_review": False,
                "review_kind": "ai",
                "split": assignment[units[0]]["split"],
                "as_of": "2026-10-18",
            }
        )
    prior_package = args.prior_draft.parent / "package-v2"
    prior_sources = {
        row["source_id"]: row
        for row in json.loads((prior_package / "sources.json").read_text(encoding="utf-8"))
    }
    supplements = []
    for source_id in ("F05", "F08", "F10"):
        source = prior_sources[source_id]
        assert digest((prior_package / f"{source_id}.pdf").read_bytes()) == source["pdf_sha256"]
        supplement = {
            "source_id": f"aux:{source_id}",
            "document_key": "sha256:" + source["pdf_sha256"],
            "title": source["title"],
            "official_url": source.get("url"),
            "pdf_sha256": source["pdf_sha256"],
            "review_kind": "ai",
            "purpose": "Fonte documental auxiliar; não conta como norma adicional.",
        }
        if source_id == "F10":
            raw = (prior_package / "F10.frozen.txt").read_text(encoding="utf-8")
            assert digest(raw.encode()) == source["text_sha256"]
            supplement.update(
                {
                    "source_text_sha256": source["text_sha256"],
                    "start": 39223,
                    "end": 40591,
                    "quote": raw[39223:40591],
                    "page": 16,
                    "citation_id": "aux:F10:art:34",
                }
            )
        else:
            supplement["reviewed_page_text"] = source.get("page_text", {})
        supplements.append(supplement)
    auxiliary = next(source for source in supplements if source["source_id"] == "aux:F10")
    for case in cases:
        if "n06" in case["expected_unit_ids"]:
            case["expected_source_ids"].append(auxiliary["document_key"])
            case["expected_versions"][auxiliary["document_key"]] = auxiliary["source_text_sha256"]
            case["expected_citation_ids"].append(auxiliary["citation_id"])
    args.output.mkdir(parents=True)
    (args.output / "texts").mkdir()
    for uid, text in texts.items():
        (args.output / f"texts/{uid}.txt").write_text(text, encoding="utf-8", newline="\n")
    write_jsonl(args.output / "manifest.jsonl", rows)
    human_queue = deepcopy(annotations)
    for annotation in human_queue:
        for event in annotation["events"]:
            event["resolution"] = "pending_review"
    write_jsonl(args.output / "annotations.pending-human.jsonl", human_queue)
    write_jsonl(args.output / "adjudications.ai.jsonl", adjudications)
    write_jsonl(args.output / "candidate-decisions.jsonl", propositions)
    write_jsonl(args.output / "source-origins.jsonl", origins)
    write_jsonl(args.output / "queries.ai.jsonl", cases)
    write_jsonl(args.output / "source-checks.jsonl", checks)
    write_jsonl(args.output / "supporting-evidence.jsonl", supplements)
    write_jsonl(
        args.output / "annotations.ai-adjudicated.jsonl",
        [
            {
                "schema_version": "jurix-ai-adjudicated-v1",
                "annotation": annotation,
                "adjudication": decision,
            }
            for annotation, decision in zip(annotations, adjudications, strict=True)
        ],
    )
    (args.output / "splits.json").write_text(
        json.dumps(assignment, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (args.output / "selection.json").write_bytes((args.inputs / "selection.json").read_bytes())
    integrity = {
        str(path.relative_to(args.output)).replace("\\", "/"): digest(path.read_bytes())
        for path in sorted(args.output.rglob("*"))
        if path.is_file()
    }
    (args.output / "SHA256SUMS.json").write_text(
        json.dumps(integrity, indent=2, sort_keys=True), encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "units": len(rows),
                "adjudications_ai": len(adjudications),
                "spans": sum(len(a["spans"]) for a in annotations),
                "events": sum(len(a["events"]) for a in annotations),
                "queries": len(cases),
                "human_adjudications": 0,
                "output": str(args.output),
            }
        )
    )


if __name__ == "__main__":
    main()
