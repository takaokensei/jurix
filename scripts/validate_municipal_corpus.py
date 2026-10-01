#!/usr/bin/env python3
"""Validate provenance and annotation gates for the municipal research corpus."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from urllib.parse import urlparse


def read_jsonl(path: Path) -> tuple[list[dict], list[str]]:
    records = []
    errors = []
    try:
        contents = path.read_text(encoding="utf-8")
    except OSError:
        return [], [f"{path}: arquivo de entrada não encontrado ou inacessível"]
    for line_number, line in enumerate(contents.splitlines(), 1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            errors.append(f"{path.name}:{line_number}: JSON inválido ({exc.msg})")
            continue
        if not isinstance(value, dict):
            errors.append(f"{path.name}:{line_number}: cada linha deve ser um objeto JSON")
            continue
        records.append(value)
    return records, errors


def _safe_text(root: Path, relative: str) -> tuple[str | None, str | None]:
    candidate = (root / relative).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError:
        return None, "caminho do texto sai do diretório do corpus"
    if not candidate.is_file():
        return None, "arquivo de texto não encontrado"
    return candidate.read_text(encoding="utf-8"), None


def validate_corpus(
    manifest_path: Path, annotation_path: Path, *, min_reviewed_pilot: int = 20
) -> dict:
    root = manifest_path.resolve().parent
    manifest, errors = read_jsonl(manifest_path)
    annotations, annotation_errors = read_jsonl(annotation_path)
    errors.extend(annotation_errors)
    warnings = []
    by_sapl_id = {}
    record_ids = set()
    legal_keys = set()

    for index, record in enumerate(manifest, 1):
        prefix = f"manifest:{index}"
        required = {
            "schema_version",
            "record_id",
            "sapl_id",
            "norma",
            "document",
            "text",
            "provenance",
            "license",
            "pilot",
            "human_review",
        }
        if required - record.keys():
            errors.append(f"{prefix}: campos obrigatórios ausentes")
            continue
        sapl_id = record["sapl_id"]
        if not isinstance(sapl_id, int) or sapl_id <= 0:
            errors.append(f"{prefix}: sapl_id deve ser inteiro positivo")
            continue
        if sapl_id in by_sapl_id:
            errors.append(f"{prefix}: sapl_id duplicado ({sapl_id})")
        by_sapl_id[sapl_id] = record
        record_id = record["record_id"]
        if record_id in record_ids:
            errors.append(f"{prefix}: record_id duplicado")
        record_ids.add(record_id)
        norma = record["norma"]
        if not isinstance(norma, dict) or not all(
            norma.get(key) for key in ("tipo", "numero", "ano")
        ):
            errors.append(f"{prefix}: identificação jurídica incompleta")
        else:
            legal_key = (
                str(norma["tipo"]).casefold(),
                str(norma["numero"]).casefold(),
                norma["ano"],
            )
            if legal_key in legal_keys:
                errors.append(f"{prefix}: identificador jurídico duplicado")
            legal_keys.add(legal_key)
        official_url = record["document"].get("official_url", "")
        parsed_url = urlparse(official_url)
        if parsed_url.scheme != "https" or parsed_url.hostname != "sapl.natal.rn.leg.br":
            errors.append(f"{prefix}: documento não aponta para HTTPS oficial do SAPL Natal")
        for field in ("sha256",):
            if len(record["document"].get(field, "")) != 64:
                errors.append(f"{prefix}: hash do PDF inválido")
        text_meta = record["text"]
        text, path_error = _safe_text(root, text_meta.get("path", ""))
        if path_error:
            errors.append(f"{prefix}: {path_error}")
        elif hashlib.sha256(text.encode("utf-8")).hexdigest() != text_meta.get("sha256"):
            errors.append(f"{prefix}: hash do texto extraído não confere")
        review = record["human_review"]
        if record["pilot"] == "approved" and (
            review.get("status") != "approved"
            or not review.get("reviewer_id")
            or not review.get("reviewed_at")
        ):
            errors.append(f"{prefix}: piloto aprovado sem sign-off humano completo")
        if record["license"].get("status") != "public_record_reviewed":
            warnings.append(f"{prefix}: condição de licença/uso requer revisão antes da publicação")

    annotation_by_id = {}
    for index, annotation in enumerate(annotations, 1):
        prefix = f"annotation:{index}"
        sapl_id = annotation.get("sapl_id")
        if sapl_id not in by_sapl_id:
            errors.append(f"{prefix}: norma não consta no manifesto")
            continue
        if sapl_id in annotation_by_id:
            errors.append(f"{prefix}: mais de uma anotação por norma; consolidar/adjudicar")
        annotation_by_id[sapl_id] = annotation
        record = by_sapl_id[sapl_id]
        text, path_error = _safe_text(root, record.get("text", {}).get("path", ""))
        if path_error:
            continue
        if annotation.get("source_text_sha256") != record["text"].get("sha256"):
            errors.append(f"{prefix}: anotação usa outra revisão do texto")
        spans = annotation.get("spans", [])
        span_ids = set()
        for span in spans:
            span_id = span.get("span_id")
            if span_id in span_ids:
                errors.append(f"{prefix}: span_id duplicado")
            span_ids.add(span_id)
            start, end = span.get("start", -1), span.get("end", -1)
            if (
                not isinstance(start, int)
                or not isinstance(end, int)
                or not (0 <= start < end <= len(text))
            ):
                errors.append(f"{prefix}: span fora dos limites do texto")
            elif text[start:end] != span.get("quote"):
                errors.append(f"{prefix}: citação do span não corresponde ao texto-fonte")
        for span in spans:
            if span.get("parent_id") is not None and span["parent_id"] not in span_ids:
                errors.append(f"{prefix}: pai do span não existe na mesma norma")
        for event in annotation.get("events", []):
            if event.get("source_span_id") not in span_ids:
                errors.append(f"{prefix}: evento referencia span de origem inexistente")
            if event.get("resolution") == "resolved":
                target_id = event.get("target_sapl_id")
                if target_id not in by_sapl_id or not event.get("target_device_key"):
                    errors.append(f"{prefix}: evento resolvido sem alvo rastreável no corpus")

    reviewed = {
        sapl_id
        for sapl_id, record in by_sapl_id.items()
        if record.get("pilot") == "approved"
        and record.get("human_review", {}).get("status") == "approved"
        and record.get("human_review", {}).get("reviewer_id")
        and record.get("human_review", {}).get("reviewed_at")
        and sapl_id in annotation_by_id
        and annotation_by_id[sapl_id].get("adjudication_status") == "adjudicated"
        and annotation_by_id[sapl_id].get("annotator_id")
        and annotation_by_id[sapl_id].get("reviewer_id")
    }
    if len(reviewed) < min_reviewed_pilot:
        warnings.append(
            f"gate científico bloqueado: {len(reviewed)}/{min_reviewed_pilot} normas-piloto anotadas e adjudicadas por humanos"
        )
    return {
        "valid": not errors,
        "release_ready": not errors and len(reviewed) >= min_reviewed_pilot and not warnings,
        "manifest_records": len(manifest),
        "annotations": len(annotations),
        "reviewed_pilot_norms": len(reviewed),
        "errors": errors,
        "warnings": warnings,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True, help="Manifesto JSONL")
    parser.add_argument("--annotations", type=Path, required=True, help="Anotações JSONL")
    parser.add_argument("--min-reviewed-pilot", type=int, default=20)
    args = parser.parse_args()
    report = validate_corpus(
        args.manifest, args.annotations, min_reviewed_pilot=args.min_reviewed_pilot
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if report["errors"]:
        return 2
    return 0 if report["release_ready"] else 3


if __name__ == "__main__":
    raise SystemExit(main())
