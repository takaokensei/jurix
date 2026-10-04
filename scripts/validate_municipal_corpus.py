#!/usr/bin/env python3
"""Validate provenance and annotation gates for the municipal research corpus."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import date, datetime
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


def _validate_v1_corpus(
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


_SHA256_RE = re.compile(r"^[a-f0-9]{64}$")
_V2_ACTIONS = {"REVOGA", "ALTERA", "ADICIONA", "SUBSTITUI", "REGULAMENTA", "REFERENCIA"}


def _is_nonempty_string(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _is_one_of(value: object, allowed: set[str]) -> bool:
    return isinstance(value, str) and value in allowed


def _safe_archive_ref(value: object) -> bool:
    if not _is_nonempty_string(value):
        return False
    normalized = value.replace("\\", "/")
    path = Path(normalized)
    return not path.is_absolute() and ".." not in normalized.split("/") and not re.match(r"^[A-Za-z]:", normalized)


def _valid_datetime(value: object) -> bool:
    if not isinstance(value, str):
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None


def _valid_date(value: object) -> bool:
    if not isinstance(value, str):
        return False
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True


def _validate_review_object(review: object, *, status_key: str, allowed_statuses: set[str]) -> bool:
    return (
        isinstance(review, dict)
        and _is_one_of(review.get(status_key), allowed_statuses)
        and _is_one_of(review.get("review_kind"), {"synthetic", "human"})
        and (review.get("reviewer_id") is None or _is_nonempty_string(review.get("reviewer_id")))
        and (review.get("reviewed_at") is None or _valid_datetime(review.get("reviewed_at")))
    )


def _validate_v2_corpus(
    manifest_path: Path, annotation_path: Path, *, min_reviewed_pilot: int = 20
) -> dict:
    root = manifest_path.resolve().parent
    manifest, errors = read_jsonl(manifest_path)
    annotations, annotation_errors = read_jsonl(annotation_path)
    errors.extend(annotation_errors)
    warnings: list[str] = []
    documents: dict[str, dict] = {}
    texts: dict[str, str] = {}
    norma_identities: dict[str, tuple] = {}
    norma_keys: set[str] = set()
    document_keys: set[str] = set()
    reviewed_normas: set[str] = set()
    reviewed_documents: set[str] = set()
    manifest_reviewed_normas: set[str] = set()
    manifest_reviewed_documents: set[str] = set()
    annotation_reviewed_normas: set[str] = set()
    annotation_reviewed_documents: set[str] = set()

    for index, record in enumerate(manifest, 1):
        prefix = f"manifest.v2:{index}"
        if record.get("schema_version") != 2:
            errors.append(f"{prefix}: versão do schema deve ser 2; registros v1 não podem ser misturados")
            continue
        required = {"norma_key", "document_key", "sapl_id", "norma", "document", "text", "provenance", "condition_of_use", "pilot", "human_review"}
        if required - record.keys():
            errors.append(f"{prefix}: campos obrigatórios ausentes")
            continue
        norma_key = record["norma_key"]
        document_key = record["document_key"]
        if not _is_nonempty_string(norma_key) or not _is_nonempty_string(document_key):
            errors.append(f"{prefix}: norma_key/document_key devem ser strings não vazias")
            continue
        if document_key in document_keys:
            errors.append(f"{prefix}: document_key duplicado")
            continue
        document_keys.add(document_key)
        norma_keys.add(norma_key)
        norma = record["norma"]
        identity_valid = isinstance(norma, dict) and all(
            _is_nonempty_string(norma.get(field)) for field in ("tipo", "numero", "jurisdicao")
        ) and not (
            norma.get("ano") is not None
            and (not isinstance(norma["ano"], int) or not 1000 <= norma["ano"] <= 9999)
        )
        if not identity_valid:
            errors.append(f"{prefix}: identidade normativa incompleta ou inválida")
        else:
            identity = (norma["tipo"].casefold(), norma["numero"].casefold(), norma.get("ano"), norma["jurisdicao"].casefold())
            if norma_key in norma_identities and norma_identities[norma_key] != identity:
                errors.append(f"{prefix}: norma_key reutilizada com identidade jurídica divergente")
            norma_identities[norma_key] = identity

        sapl_id = record["sapl_id"]
        if sapl_id is not None and (not isinstance(sapl_id, int) or sapl_id < 1):
            errors.append(f"{prefix}: sapl_id deve ser null ou inteiro positivo")
        document = record["document"]
        if not isinstance(document, dict):
            errors.append(f"{prefix}: document deve ser objeto")
            continue
        source_kind = document.get("source_kind")
        if not isinstance(source_kind, str) or source_kind not in {"archive", "sapl", "official_gazette"}:
            errors.append(f"{prefix}: source_kind inválido")
        if not _is_nonempty_string(document.get("source_ref")):
            errors.append(f"{prefix}: source_ref obrigatório")
        elif source_kind == "archive" and not _safe_archive_ref(document["source_ref"]):
            errors.append(f"{prefix}: source_ref do acervo deve ser relativo e contido")
        document_hash = document.get("sha256")
        if not isinstance(document_hash, str) or not _SHA256_RE.fullmatch(document_hash):
            errors.append(f"{prefix}: hash do documento inválido")
        archive_hash = document.get("archive_sha256")
        if archive_hash is not None and (not isinstance(archive_hash, str) or not _SHA256_RE.fullmatch(archive_hash)):
            errors.append(f"{prefix}: hash do acervo inválido")
        official_url = document.get("official_url")
        if official_url is not None:
            parsed = urlparse(official_url if isinstance(official_url, str) else "")
            if parsed.scheme != "https" or parsed.hostname != "sapl.natal.rn.leg.br":
                errors.append(f"{prefix}: URL oficial não é um endereço HTTPS do SAPL Natal")
        if source_kind == "sapl" and official_url is None:
            errors.append(f"{prefix}: documento SAPL requer URL oficial confirmada")
        if source_kind == "sapl" and sapl_id is None:
            errors.append(f"{prefix}: documento SAPL requer sapl_id confirmado")
        if not _is_one_of(document.get("role"), {"original", "republicacao", "retificacao", "anexo", "indeterminado"}):
            errors.append(f"{prefix}: role documental inválida")
        entry_index = document.get("entry_index")
        if entry_index is not None and (not isinstance(entry_index, int) or entry_index < 0):
            errors.append(f"{prefix}: entry_index inválido")
        blob_path = document.get("pdf_path")
        if blob_path is not None:
            if not _is_nonempty_string(blob_path):
                errors.append(f"{prefix}: caminho do PDF inválido")
            else:
                candidate = (root / blob_path).resolve()
                try:
                    candidate.relative_to(root.resolve())
                    payload = candidate.read_bytes()
                    if hashlib.sha256(payload).hexdigest() != document_hash:
                        errors.append(f"{prefix}: hash do PDF não confere")
                except (OSError, ValueError, TypeError):
                    errors.append(f"{prefix}: PDF não encontrado ou caminho inseguro")

        text_meta = record["text"]
        if not isinstance(text_meta, dict):
            errors.append(f"{prefix}: text deve ser objeto")
            continue
        text_path = text_meta.get("path", "")
        text, path_error = _safe_text(root, text_path) if _is_nonempty_string(text_path) else (None, "caminho do texto inválido")
        if path_error:
            errors.append(f"{prefix}: {path_error}")
        elif not isinstance(text_meta.get("sha256"), str) or not _SHA256_RE.fullmatch(text_meta["sha256"]):
            errors.append(f"{prefix}: hash do texto inválido")
        elif hashlib.sha256(text.encode("utf-8")).hexdigest() != text_meta["sha256"]:
            errors.append(f"{prefix}: hash do texto extraído não confere")
        else:
            texts[document_key] = text
        if not _is_nonempty_string(text_meta.get("text_version")) or not _is_nonempty_string(text_meta.get("extractor_version")):
            errors.append(f"{prefix}: revisão textual sem versão de texto/extrator")
        if not _is_one_of(text_meta.get("ocr_status"), {
            "native", "ocr_reviewed", "ocr_unreviewed", "mixed_reviewed", "mixed_unreviewed", "unreadable"
        }):
            errors.append(f"{prefix}: ocr_status inválido")
        provenance = record["provenance"]
        if not isinstance(provenance, dict) or not _valid_datetime(provenance.get("retrieved_at")) or not _is_nonempty_string(provenance.get("selection_rationale")):
            errors.append(f"{prefix}: proveniência incompleta ou data inválida")
        if not _is_one_of(record.get("condition_of_use"), {"unknown", "public_record_reviewed", "permission_required", "licensed"}):
            errors.append(f"{prefix}: condition_of_use inválida")
        if not _is_one_of(record.get("pilot"), {"not_selected", "candidate", "technical_pilot", "approved"}):
            errors.append(f"{prefix}: estado de piloto inválido")
        if record.get("condition_of_use") != "public_record_reviewed":
            warnings.append(f"{prefix}: condição de uso requer revisão antes da publicação")
        human = record["human_review"] if isinstance(record["human_review"], dict) else {}
        if not _validate_review_object(
            human,
            status_key="status",
            allowed_statuses={"not_reviewed", "in_review", "approved", "rejected"},
        ):
            errors.append(f"{prefix}: contrato de human_review inválido")
        if isinstance(human, dict) and (
            record.get("pilot") == "approved"
            and human.get("status") == "approved"
            and human.get("review_kind") == "human"
            and _is_nonempty_string(human.get("reviewer_id"))
            and _is_nonempty_string(human.get("reviewed_at"))
            and record.get("condition_of_use") == "public_record_reviewed"
        ):
            manifest_reviewed_normas.add(norma_key)
            manifest_reviewed_documents.add(document_key)
        documents[document_key] = record

    annotation_ids: set[str] = set()
    annotations_by_document: dict[str, dict] = {}
    device_keys: set[tuple[str, str]] = set()
    pending_events: list[tuple[str, dict, dict]] = []
    for index, annotation in enumerate(annotations, 1):
        prefix = f"annotation.v2:{index}"
        if annotation.get("schema_version") != 2:
            errors.append(f"{prefix}: versão do schema deve ser 2; registros v1 não podem ser misturados")
            continue
        required = {"annotation_id", "norma_key", "document_key", "revision", "scope", "annotator_id", "review", "spans", "events"}
        if required - annotation.keys():
            errors.append(f"{prefix}: campos obrigatórios ausentes")
            continue
        annotation_id = annotation.get("annotation_id")
        document_key = annotation.get("document_key")
        if not _is_nonempty_string(annotation_id) or annotation_id in annotation_ids:
            errors.append(f"{prefix}: annotation_id vazio ou duplicado")
            continue
        annotation_ids.add(annotation_id)
        record = documents.get(document_key)
        if record is None:
            errors.append(f"{prefix}: documento não consta no manifesto v2")
            continue
        if annotation.get("norma_key") != record["norma_key"]:
            errors.append(f"{prefix}: documento vinculado a norma_key divergente")
        if document_key in annotations_by_document:
            errors.append(f"{prefix}: mais de uma anotação para o mesmo document_key/revisão")
        annotations_by_document[document_key] = annotation
        revision = annotation["revision"]
        if not isinstance(revision, dict) or not all(
            _is_nonempty_string(revision.get(field))
            for field in ("source_text_sha256", "text_version", "extractor_version")
        ):
            errors.append(f"{prefix}: metadados da revisão textual inválidos")
            continue
        text_meta = record["text"]
        if (
            revision.get("source_text_sha256") != text_meta.get("sha256")
            or revision.get("text_version") != text_meta.get("text_version")
            or revision.get("extractor_version") != text_meta.get("extractor_version")
        ):
            errors.append(f"{prefix}: anotação mistura hash ou revisão textual do documento")
        text = texts.get(document_key)
        if text is None:
            continue
        scope = annotation["scope"]
        if (
            not isinstance(scope, dict)
            or not _is_one_of(scope.get("kind"), {"device", "norma", "temporal"})
            or not _is_nonempty_string(scope.get("jurisdiction"))
            or (scope.get("as_of") is not None and not _valid_date(scope.get("as_of")))
        ):
            errors.append(f"{prefix}: escopo da anotação inválido")
        if not _is_nonempty_string(annotation.get("annotator_id")):
            errors.append(f"{prefix}: annotator_id obrigatório")
        spans = annotation["spans"]
        if not isinstance(spans, list):
            errors.append(f"{prefix}: spans deve ser lista")
            continue
        span_ids: set[str] = set()
        local_device_keys: set[str] = set()
        for span in spans:
            if not isinstance(span, dict):
                errors.append(f"{prefix}: span deve ser objeto")
                continue
            span_id = span.get("span_id")
            if not _is_nonempty_string(span_id) or span_id in span_ids:
                errors.append(f"{prefix}: span_id vazio ou duplicado")
                continue
            span_ids.add(span_id)
            if not _is_one_of(span.get("label"), {
                "artigo", "paragrafo", "paragrafo_unico", "inciso", "alinea", "item", "anexo"
            }):
                errors.append(f"{prefix}: label de span inválido")
            device_key = span.get("device_key")
            if not _is_nonempty_string(device_key) or device_key in local_device_keys:
                errors.append(f"{prefix}: device_key vazio ou duplicado no documento")
            elif (document_key, device_key) in device_keys:
                errors.append(f"{prefix}: device_key duplicada")
            else:
                local_device_keys.add(device_key)
                device_keys.add((document_key, device_key))
            start, end = span.get("start"), span.get("end")
            if not isinstance(start, int) or not isinstance(end, int) or not (0 <= start < end <= len(text)):
                errors.append(f"{prefix}: span fora dos limites do texto congelado")
            elif text[start:end] != span.get("quote"):
                errors.append(f"{prefix}: quote do span não corresponde ao texto congelado")
        for span in spans:
            parent = span.get("parent_device_key") if isinstance(span, dict) else None
            if parent is not None and parent not in local_device_keys:
                errors.append(f"{prefix}: parent_device_key não existe no mesmo documento")
        if not isinstance(annotation["events"], list):
            errors.append(f"{prefix}: events deve ser lista")
            continue
        for event in annotation["events"]:
            if not isinstance(event, dict):
                errors.append(f"{prefix}: evento deve ser objeto")
                continue
            if not _is_one_of(event.get("action"), _V2_ACTIONS):
                errors.append(f"{prefix}: ação normativa v2 inválida")
            if event.get("source_span_id") not in span_ids:
                errors.append(f"{prefix}: evento referencia span de origem inexistente")
            evidence = event.get("evidence", {})
            effective_date = event.get("effective_date", {})
            if not isinstance(effective_date, dict) or not _is_one_of(effective_date.get("status"), {
                "unknown", "candidate", "confirmed"
            }):
                errors.append(f"{prefix}: metadados de data de efeito inválidos")
            elif effective_date.get("value") is not None and not _valid_date(effective_date["value"]):
                errors.append(f"{prefix}: data de efeito inválida")
            if event.get("revision") != revision.get("text_version"):
                errors.append(f"{prefix}: evento usa revisão diferente da anotação")
            if not isinstance(evidence, dict):
                errors.append(f"{prefix}: evidence deve ser objeto")
                continue
            start, end = evidence.get("start"), evidence.get("end")
            if evidence.get("source_text_sha256") != text_meta.get("sha256"):
                errors.append(f"{prefix}: evidência usa hash/revisão textual divergente")
            elif not isinstance(start, int) or not isinstance(end, int) or not (0 <= start < end <= len(text) and text[start:end] == evidence.get("quote")):
                errors.append(f"{prefix}: quote/span da evidência não corresponde à fonte")
            if event.get("resolution") == "resolved" and (
                not _is_nonempty_string(event.get("target_norma_key"))
                or not _is_nonempty_string(event.get("target_device_key"))
            ):
                errors.append(f"{prefix}: relação resolvida sem norma/dispositivo tipados")
            pending_events.append((prefix, event, record))
        review = annotation["review"]
        if not _validate_review_object(
            review,
            status_key="status",
            allowed_statuses={"pending", "adjudicated", "excluded"},
        ):
            errors.append(f"{prefix}: contrato de revisão da anotação inválido")
        if isinstance(review, dict) and (
            review.get("status") == "adjudicated"
            and review.get("review_kind") == "human"
            and _is_nonempty_string(review.get("reviewer_id"))
            and _is_nonempty_string(review.get("reviewed_at"))
            and isinstance(record.get("human_review"), dict)
            and record["human_review"].get("review_kind") == "human"
            and record["human_review"].get("status") == "approved"
        ):
            annotation_reviewed_normas.add(record["norma_key"])
            annotation_reviewed_documents.add(document_key)

    reviewed_normas = manifest_reviewed_normas & annotation_reviewed_normas
    reviewed_documents = manifest_reviewed_documents & annotation_reviewed_documents

    known_target_devices = {
        (documents[doc_key]["norma_key"], device_key)
        for doc_key, device_key in device_keys
        if doc_key in documents
    }
    for prefix, event, _source_record in pending_events:
        if event.get("resolution") == "resolved":
            target = (event.get("target_norma_key"), event.get("target_device_key"))
            if target[0] not in norma_keys or target not in known_target_devices:
                errors.append(f"{prefix}: relação resolvida aponta para alvo ausente no corpus")

    reviewed_count = len(reviewed_normas)
    if reviewed_count < min_reviewed_pilot:
        warnings.append(
            f"gate científico bloqueado: {reviewed_count}/{min_reviewed_pilot} normas distintas revisadas e adjudicadas por humanos"
        )
    return {
        "valid": not errors,
        "release_ready": not errors and reviewed_count >= min_reviewed_pilot and not warnings,
        "schema_version": 2,
        "manifest_records": len(manifest),
        "normas_distintas": len(norma_keys),
        "annotations": len(annotations),
        "reviewed_pilot_documents": len(reviewed_documents),
        "reviewed_pilot_norms": reviewed_count,
        "errors": errors,
        "warnings": warnings,
    }


def validate_corpus(
    manifest_path: Path, annotation_path: Path, *, min_reviewed_pilot: int = 20
) -> dict:
    """Dispatch v1/v2 without changing the legacy v1 corpus contract."""
    manifest, _ = read_jsonl(manifest_path)
    annotations, _ = read_jsonl(annotation_path)
    versions = {
        record.get("schema_version")
        for record in (*manifest, *annotations)
        if isinstance(record, dict)
    }
    if versions <= {1}:
        return _validate_v1_corpus(
            manifest_path, annotation_path, min_reviewed_pilot=min_reviewed_pilot
        )
    if versions != {2}:
        return {
            "valid": False,
            "release_ready": False,
            "manifest_records": len(manifest),
            "annotations": len(annotations),
            "reviewed_pilot_norms": 0,
            "errors": ["mistura de versões de schema ou versão não suportada"],
            "warnings": [],
        }
    return _validate_v2_corpus(
        manifest_path, annotation_path, min_reviewed_pilot=min_reviewed_pilot
    )


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
