"""Safe, structured exports for answer citations and their provenance."""

from __future__ import annotations

import json
import re
from datetime import UTC, date, datetime
from typing import Any
from urllib.parse import urlsplit, urlunsplit

_MAX_EXCERPT_LENGTH = 4_000
_LOCAL_PDF_PATH = re.compile(r"^/normas/documentos/[0-9a-fA-F-]{36}/pdf/(?:#page=\d+)?$")
_SHA256 = re.compile(r"^[0-9a-fA-F]{64}$")
_GRAPH_ACTIONS = {"ALTERA", "SUBSTITUI", "ADICIONA", "REVOGA", "REFERENCIA"}


def _text(value: Any, limit: int = 500) -> str | None:
    if value is None:
        return None
    result = " ".join(str(value).split())[:limit].strip()
    return result or None


def _date(value: Any) -> str | None:
    if isinstance(value, date | datetime):
        return value.date().isoformat() if isinstance(value, datetime) else value.isoformat()
    value = _text(value, 32)
    if not value:
        return None
    try:
        return date.fromisoformat(value[:10]).isoformat()
    except ValueError:
        return None


def _aware_datetime(value: Any) -> str | None:
    if isinstance(value, datetime):
        parsed = value
    else:
        value = _text(value, 48)
        if not value:
            return None
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.isoformat(timespec="seconds")


def _safe_coverage_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value >= 0 else None
    if isinstance(value, str) and value.isdecimal():
        return int(value)
    return None


def _safe_coverage_date(value: Any) -> str | None:
    if isinstance(value, datetime) or value is None:
        return None
    candidate = value.isoformat() if isinstance(value, date) else value
    if not isinstance(candidate, str):
        return None
    if not candidate or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", candidate):
        return None
    try:
        parsed = date.fromisoformat(candidate)
    except ValueError:
        return None
    return candidate if parsed.isoformat() == candidate else None


def _safe_corpus_coverage(coverage: Any) -> dict[str, Any] | None:
    """Keep the Python evidence package aligned with the browser's safe DTO."""
    if not isinstance(coverage, dict):
        return None

    statuses = {"unknown", "partial", "reviewed"}

    def safe_status(value: Any) -> str:
        return value if isinstance(value, str) and value in statuses else "unknown"

    def safe_interval(value: Any, *, include_scope: bool = False) -> dict[str, Any] | None:
        if not isinstance(value, dict):
            return None
        interval = {}
        if include_scope:
            interval.update(
                {
                    "source": _text(value.get("source"), 80),
                    "jurisdiction": _text(value.get("jurisdiction"), 100),
                    "series": _text(value.get("series"), 80),
                }
            )
        interval.update(
            {
                "start": _safe_coverage_date(value.get("start")),
                "end": _safe_coverage_date(value.get("end")),
            }
        )
        return interval if interval.get("start") or interval.get("end") else None

    def safe_scope(value: Any) -> dict[str, Any] | None:
        if not isinstance(value, dict):
            return None
        raw_intervals = value.get("missing_intervals")
        intervals = None
        if isinstance(raw_intervals, list):
            intervals = [
                interval
                for raw_interval in raw_intervals[:100]
                if (interval := safe_interval(raw_interval)) is not None
            ]
        return {
            "source": _text(value.get("source"), 80),
            "jurisdiction": _text(value.get("jurisdiction"), 100),
            "series": _text(value.get("series"), 80),
            "period_start": _safe_coverage_date(value.get("period_start")),
            "period_end": _safe_coverage_date(value.get("period_end")),
            "checked_until": _safe_coverage_date(value.get("checked_until")),
            "source_checksum": (
                str(value["source_checksum"]).lower()
                if isinstance(value.get("source_checksum"), str)
                and _SHA256.fullmatch(value["source_checksum"])
                else None
            ),
            "coverage_status": safe_status(value.get("coverage_status")),
            "missing_intervals": intervals,
            "pending_review": _safe_coverage_int(value.get("pending_review")),
            "last_success_at": _aware_datetime(value.get("last_success_at")),
        }

    revision = coverage.get("corpus_revision")
    revision = revision if isinstance(revision, dict) else {}
    raw_scopes = coverage.get("sources_checked")
    scopes = (
        [scope for raw_scope in raw_scopes[:100] if (scope := safe_scope(raw_scope)) is not None]
        if isinstance(raw_scopes, list)
        else []
    )
    raw_missing = coverage.get("missing_intervals")
    missing = (
        [
            interval
            for raw_interval in raw_missing[:100]
            if (interval := safe_interval(raw_interval, include_scope=True)) is not None
        ]
        if isinstance(raw_missing, list)
        else None
    )
    reason = coverage.get("reason")
    allowed_reasons = {
        "no_reviewed_coverage_scope",
        "registered_scopes_only_not_a_universal_completeness_claim",
    }
    return {
        "coverage_status": safe_status(coverage.get("coverage_status")),
        "corpus_revision": {
            "revision": _safe_coverage_int(revision.get("revision")),
            "digest": (
                str(revision["digest"]).lower()
                if isinstance(revision.get("digest"), str)
                and _SHA256.fullmatch(revision["digest"])
                else None
            ),
        },
        "scope_limited": coverage.get("scope_limited") is True,
        "checked_until": _safe_coverage_date(coverage.get("checked_until")),
        "sources_checked": scopes,
        "missing_intervals": missing,
        "pending_review": _safe_coverage_int(coverage.get("pending_review")),
        "reason": reason if isinstance(reason, str) and reason in allowed_reasons else None,
    }


def _safe_url(value: Any, *, allow_local_pdf: bool = False) -> str | None:
    candidate = _text(value, 2_000)
    if not candidate or any(char in candidate for char in '<>"\\'):
        return None
    if allow_local_pdf and _LOCAL_PDF_PATH.fullmatch(candidate):
        return candidate
    parsed = urlsplit(candidate)
    if parsed.scheme in {"http", "https"} and parsed.hostname and not parsed.username:
        # A legal citation identifies the source itself, not a brittle browser
        # text-fragment generated from a snippet that may later change.
        fragment = "" if parsed.fragment.startswith(":~:text=") else parsed.fragment
        return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, parsed.query, fragment))
    return None


def _safe_graph_relation(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    action = str(value.get("action") or "").upper()
    if action not in _GRAPH_ACTIONS:
        return None
    result: dict[str, Any] = {"action": action}
    for key in (
        "event_id", "intent", "role", "label", "review_status", "effective_status", "resolution"
    ):
        safe = _text(value.get(key), 160)
        if safe:
            result[key] = safe
    for key in ("effective_on", "publication_on"):
        if (safe := _date(value.get(key))):
            result[key] = safe
    for key in ("source_norma_id", "target_norma_id"):
        raw = value.get(key)
        if isinstance(raw, int) and not isinstance(raw, bool) and raw > 0:
            result[key] = raw
    for key in ("source_device_key", "target_device_key"):
        raw = value.get(key)
        if isinstance(raw, str) and _SHA256.fullmatch(raw):
            result[key] = raw.lower()
    quote = _text(value.get("quote"), 1200)
    if quote:
        result["quote"] = quote
    return result


def _safe_projection_coverage(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    result: dict[str, Any] = {}
    for key in ("as_of",):
        if (safe := _date(value.get(key))):
            result[key] = safe
    for key in ("version_hash", "input_hash"):
        raw = value.get(key)
        if isinstance(raw, str) and _SHA256.fullmatch(raw):
            result[key] = raw.lower()
    for key in ("snapshot_id", "projected_devices", "selected_devices"):
        parsed = _safe_coverage_int(value.get(key))
        if parsed is not None:
            result[key] = parsed
    for key in ("status", "policy"):
        if (safe := _text(value.get(key), 80)):
            result[key] = safe
    if isinstance(value.get("complete"), bool):
        result["complete"] = value["complete"]
    if isinstance(value.get("citation_anchor_unavailable"), bool):
        result["citation_anchor_unavailable"] = value["citation_anchor_unavailable"]
    return result or None


def _verification_limit(source: dict[str, Any], coverage: dict[str, Any] | None) -> str:
    if source.get("evidence_scope") == "isolated_qa_archive":
        return "Extração de acervo histórico local; revisão jurídica e consolidação não são atestadas por este pacote."
    if source.get("temporal_version"):
        if coverage and coverage.get("complete") is True:
            return "Projeção registrada para a data indicada; não determina aplicabilidade ao caso concreto."
        return "Projeção histórica parcial ou incompleta; a redação integral não foi confirmada."
    return "As evidências recuperadas não certificam exaustividade do corpus nem aplicabilidade ao caso concreto."


def _source_dto(source: dict[str, Any], *, include_excerpt: bool) -> dict[str, Any] | None:
    citation_id = _text(source.get("citation_id"), 240)
    citation_index = source.get("citation_index")
    try:
        citation_index = int(citation_index)
    except (TypeError, ValueError):
        citation_index = None
    if citation_index is not None and citation_index <= 0:
        citation_index = None
    if not citation_id and citation_index is None:
        return None

    temporal = source.get("temporal_version")
    temporal_dto = None
    if isinstance(temporal, dict):
        version_hash = str(temporal.get("version_hash") or "")
        if _SHA256.fullmatch(version_hash) and _date(temporal.get("as_of")):
            temporal_dto = {
                "as_of": _date(temporal.get("as_of")),
                "legal_status": _text(temporal.get("legal_status"), 32),
                "version_hash": version_hash.lower(),
                "policy": _text(temporal.get("policy"), 100),
                "effective_on": _date(temporal.get("effective_on")),
                "source_document_id": _text(temporal.get("source_document_id"), 64),
            }
            input_hash = temporal.get("input_hash")
            if isinstance(input_hash, str) and _SHA256.fullmatch(input_hash):
                temporal_dto["input_hash"] = input_hash.lower()
            snapshot_id = _safe_coverage_int(temporal.get("snapshot_id"))
            if snapshot_id is not None:
                temporal_dto["snapshot_id"] = snapshot_id
            temporal_dto["status_note"] = _text(temporal.get("status_note"), 240)

    document_hash = source.get("document_sha256") or source.get("content_sha256")
    if not isinstance(document_hash, str) or not _SHA256.fullmatch(document_hash):
        document_hash = None

    local_pdf = _safe_url(source.get("local_pdf_url"), allow_local_pdf=True)
    official_url = _safe_url(source.get("source_url")) or _safe_url(source.get("pdf_url"))
    if not official_url:
        official_url = _safe_url(source.get("sapl_url"))

    raw_span = source.get("span")
    safe_span = None
    if isinstance(raw_span, dict):
        start, end = raw_span.get("start"), raw_span.get("end")
        if isinstance(start, int) and isinstance(end, int) and 0 <= start <= end:
            safe_span = {"start": start, "end": end}

    projection_coverage = _safe_projection_coverage(source.get("coverage"))
    row = {
        "citation_id": citation_id,
        "citation_index": citation_index,
        "label": _text(source.get("citation_label"), 500),
        "norma": _text(source.get("norma_ref"), 240),
        "norma_id": _text(source.get("norma_id"), 64),
        "dispositivo": _text(source.get("dispositivo_ref"), 240),
        "evidence_type": _text(source.get("source_type"), 120),
        "contribution": _text(source.get("contribution"), 240),
        "source_kind": _text(source.get("source_kind"), 80),
        "status_label": _text(source.get("status_label"), 160),
        "matter_status": source.get("matter_status")
        if isinstance(source.get("matter_status"), bool)
        else None,
        "matter_result": _text(source.get("matter_result"), 240),
        "evidence_scope": _text(source.get("evidence_scope"), 80),
        "publication_date": _date(source.get("data_publicacao")),
        "consulted_at": _aware_datetime(source.get("consulted_at")),
        "effective_date": _date(source.get("data_vigencia")),
        "temporal_status": _text(source.get("temporal_status"), 48),
        "temporal_version": temporal_dto,
        "graph_relation": _safe_graph_relation(source.get("graph_relation")),
        "projection_coverage": projection_coverage,
        "verification_limit": _verification_limit(source, projection_coverage),
        "document_id": _text(source.get("source_id") or source.get("document_id"), 64),
        "document_sha256": document_hash.lower() if document_hash else None,
        "page": source.get("page")
        if isinstance(source.get("page"), int) and source.get("page") > 0
        else None,
        "span": safe_span,
        "span_basis": _text(source.get("span_basis"), 80),
        "official_url": official_url,
        "local_pdf_url": local_pdf,
    }
    if include_excerpt:
        row["excerpt"] = _text(
            source.get("evidence_text") or source.get("full_text") or source.get("text"),
            _MAX_EXCERPT_LENGTH,
        )
    return row


def build_evidence_package(
    sources: list[dict[str, Any]],
    *,
    corpus_revision: dict[str, Any] | None = None,
    corpus_coverage: dict[str, Any] | None = None,
    generated_at: datetime | None = None,
    include_excerpts: bool = True,
) -> dict[str, Any]:
    """Build a versioned export DTO without copying arbitrary source fields."""
    revision = {}
    if isinstance(corpus_revision, dict):
        for key in ("revision", "completeness", "updated_at", "source"):
            value = corpus_revision.get(key)
            if key == "updated_at":
                value = _date(value)
            elif key == "completeness":
                value = value if value in {"complete", "partial", "unknown", "incomplete"} else None
            else:
                value = _text(value, 120)
            if value:
                revision[key] = value
        digest = corpus_revision.get("digest")
        if isinstance(digest, str) and _SHA256.fullmatch(digest):
            revision["digest"] = digest.lower()

    rows = [
        dto
        for source in sources or []
        if isinstance(source, dict)
        if (dto := _source_dto(source, include_excerpt=include_excerpts)) is not None
    ]
    rows.sort(
        key=lambda row: (
            row["citation_index"] is None,
            row["citation_index"] or 0,
            row["citation_id"] or "",
        )
    )
    timestamp = generated_at or datetime.now(UTC)
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=UTC)
    return {
        "schema_version": "jurix-evidence-v1",
        "generated_at": timestamp.astimezone(UTC).isoformat(),
        "corpus_revision": revision or None,
        "corpus_coverage": _safe_corpus_coverage(corpus_coverage),
        "sources": rows,
    }


def _markdown_label(value: Any) -> str:
    return (
        str(value or "Fonte jurídica").replace("\\", "\\\\").replace("[", "\\[").replace("]", "\\]")
    )


def render_evidence_markdown(package: dict[str, Any]) -> str:
    """Render a compact, provenance-preserving Markdown reference list."""
    lines = ["## Referências e evidências", ""]
    revision = package.get("corpus_revision")
    if isinstance(revision, dict):
        label = revision.get("revision") or "não informada"
        completeness = revision.get("completeness") or "não verificada"
        lines.extend([f"Corpus: `{label}` — completude: **{completeness}**.", ""])
    coverage = _safe_corpus_coverage(package.get("corpus_coverage"))
    if coverage is None:
        lines.extend(["Cobertura do acervo: **não informada**.", ""])
    else:
        status_labels = {
            "unknown": "não verificada",
            "partial": "parcial",
            "reviewed": "revisada somente nos escopos listados",
        }
        lines.append(f"Cobertura do acervo: **{status_labels[coverage['coverage_status']]}**.")
        if coverage["checked_until"]:
            lines.append(f"Corte verificado: **{coverage['checked_until']}**.")
        if coverage["pending_review"] is not None:
            lines.append(f"Documentos pendentes de revisão: **{coverage['pending_review']}**.")
        if coverage["scope_limited"]:
            lines.append("A cobertura abaixo é limitada aos escopos declarados; não comprova completude universal.")
        for scope in coverage["sources_checked"]:
            identity = " · ".join(
                _markdown_label(value)
                for value in (scope["source"], scope["jurisdiction"], scope["series"])
                if value
            ) or "Escopo sem identificação completa"
            period_start = scope["period_start"] or "início não informado"
            period_end = scope["period_end"] or "fim não informado"
            scope_status = status_labels[scope["coverage_status"]]
            line = f"- {identity}: {period_start} a {period_end}; cobertura {scope_status}"
            if scope["checked_until"]:
                line += f", conferida até {scope['checked_until']}"
            if scope["pending_review"] is not None:
                line += f", {scope['pending_review']} pendência(s)"
            lines.append(line + ".")
        for interval in coverage["missing_intervals"] or []:
            identity = " · ".join(
                _markdown_label(value)
                for value in (interval["source"], interval["jurisdiction"], interval["series"])
                if value
            )
            start = interval["start"] or "início não informado"
            end = interval["end"] or "fim não informado"
            prefix = f"{identity}: " if identity else ""
            lines.append(f"- Intervalo sem cobertura registrada — {prefix}{start} a {end}.")
        if coverage["reason"] == "no_reviewed_coverage_scope":
            lines.append("Nenhum escopo de cobertura revisada foi registrado.")
        elif coverage["reason"] == "registered_scopes_only_not_a_universal_completeness_claim":
            lines.append("Os escopos registrados não constituem declaração de completude de todo o acervo.")
        lines.append("")
    for source in package.get("sources", []):
        label = _markdown_label(source.get("label") or source.get("norma"))
        url = source.get("official_url") or source.get("local_pdf_url")
        if url:
            lines.append(f"- [{label}](<{url}>)")
        else:
            lines.append(f"- {label}")
        details = [source.get("contribution"), source.get("evidence_type")]
        details = [str(value) for value in details if value]
        if details:
            lines.append(f"  - {'; '.join(details)}")
        if source.get("excerpt"):
            excerpt = (
                str(source["excerpt"])
                .replace("\n", " ")
                .replace("[", "\\[")
                .replace("]", "\\]")
                .strip()
            )
            excerpt = excerpt.replace("<", "&lt;").replace(">", "&gt;")
            lines.append(f"  - Evidência: “{excerpt}”")
        if source.get("document_sha256"):
            lines.append(f"  - SHA-256 do documento: `{source['document_sha256']}`")
        temporal = source.get("temporal_version")
        if temporal:
            lines.append(
                f"  - Projeção em {temporal['as_of']} · versão `{temporal['version_hash']}` · "
                f"situação: {temporal.get('legal_status') or 'não determinada'}"
            )
            if temporal.get("snapshot_id") is not None:
                lines.append(f"  - Snapshot: `{temporal['snapshot_id']}`.")
            if temporal.get("input_hash"):
                lines.append(f"  - Hash de entrada da projeção: `{temporal['input_hash']}`.")
        relation = source.get("graph_relation")
        if relation:
            event = f"evento `{relation['event_id']}`" if relation.get("event_id") else "evento normativo"
            lines.append(
                f"  - Relação: {relation['action']} · {event} · "
                f"revisão: {relation.get('review_status') or 'não informada'} · "
                f"efeito: {relation.get('effective_status') or 'não confirmado'}"
            )
            if relation.get("quote"):
                lines.append(f"  - Trecho do evento: “{relation['quote']}”")
        if source.get("projection_coverage"):
            coverage = source["projection_coverage"]
            selected = coverage.get("selected_devices")
            projected = coverage.get("projected_devices")
            if selected is not None or projected is not None:
                lines.append(
                    f"  - Cobertura da projeção: {selected if selected is not None else 'não informada'} "
                    f"selecionado(s) de {projected if projected is not None else 'total não informado'} dispositivo(s)."
                )
        if source.get("verification_limit"):
            lines.append(f"  - Limite da verificação: {source['verification_limit']}")
    if not package.get("sources"):
        lines.append("Nenhuma fonte estruturada foi fornecida para exportação.")
    lines.extend(["", f"Exportado em: {package.get('generated_at', 'não informado')}."])
    return "\n".join(lines)


def render_evidence_json(package: dict[str, Any]) -> str:
    """Serialize the safe export DTO as stable UTF-8-friendly JSON."""
    return json.dumps(package, ensure_ascii=False, indent=2, sort_keys=True)
