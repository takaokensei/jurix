"""Read-only trace for the fixed Code of Works transition QA scenario."""

from __future__ import annotations

import json
import os

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from src.apps.legislation.document_models import DocumentoNormativo
from src.processing.qa_archive_rag import (
    _EFFECTIVE_DATE_OPERATIVE_RE,
    _NORMATIVE_CHANGE_EVIDENCE_RE,
    _PROCESS_TRANSITION_EVIDENCE_RE,
    _archive_retrieval_candidates,
    _article_rows,
    _latest_extraction,
    retrieve_archive_evidence,
)

NATURAL_QUERY = (
    "Em um pedido de licenciamento de obra protocolado antes da entrada em vigor do "
    "Código de Obras atual e ainda sem despacho decisório, quais fatos e dispositivos "
    "devo conferir para saber qual regime analisar? Compare as regras de transição e "
    "revogação relevantes, cite as fontes e destaque o que permanece sem revisão jurídica."
)
EXPLICIT_QUERY = (
    "Confronte explicitamente o Art. 21 da LC nº 55/2004 com os Arts. 260, 262 e 266 "
    "da LC nº 258/2024. Quais trechos do acervo tratam da revogação, da regra de "
    "transição e da entrada em vigor? Cite as fontes e não conclua qual redação se "
    "aplica ao processo sem conferir os autos."
)
TARGET_ARTICLES = {"260", "262", "266"}


def _candidate_summary(document: DocumentoNormativo) -> dict[str, object]:
    extraction = _latest_extraction(document)
    identity = (document.metadata_json or {}).get("identity_candidate", {})
    legal_text = str(getattr(extraction, "legal_text", "") or "")
    articles = _article_rows(
        legal_text,
        page_map=getattr(extraction, "page_map_json", None),
    )
    targets = []
    for article in articles:
        number = str(article.get("numero") or "").strip()
        if number not in TARGET_ARTICLES:
            continue
        text = str(article.get("texto") or "")
        targets.append(
            {
                "article": f"Art. {number}",
                "characters": len(text),
                "transition_clause_match": bool(_PROCESS_TRANSITION_EVIDENCE_RE.search(text)),
                "normative_change_match": bool(_NORMATIVE_CHANGE_EVIDENCE_RE.search(text)),
                "operative_commencement_match": bool(_EFFECTIVE_DATE_OPERATIVE_RE.search(text)),
            }
        )

    return {
        "identity_candidate": {
            "type": identity.get("type"),
            "number": identity.get("number"),
            "year": identity.get("year"),
        },
        "extraction_status": getattr(extraction, "status", None),
        "parsed_article_count": len(articles),
        "target_articles": targets,
        "review_accepted": bool(document.accepted_extraction_id),
        "norma_linkage_created": bool(document.norma_id),
    }


def _retrieval_summary(question: str) -> list[dict[str, object]]:
    return [
        {
            "norma": row.get("norma_ref"),
            "article": row.get("dispositivo_ref"),
            "extraction_status": (row.get("coverage") or {}).get("extraction_status"),
            "review_accepted": bool((row.get("coverage") or {}).get("review_accepted")),
        }
        for row in retrieve_archive_evidence(question, limit=12)
    ]


class Command(BaseCommand):
    help = "Compara título natural e artigos explícitos no acervo QA, sem expor texto ou alterar dados."

    def handle(self, *args, **options):
        if (
            os.environ.get("JURIX_QA_ONLY") != "1"
            or os.environ.get("DJANGO_SETTINGS_MODULE")
            not in {"config.settings_normative_qa", "config.settings_normative_container_qa"}
            or not getattr(settings, "NORMATIVE_ARCHIVE_ASSISTANT_ENABLED", False)
        ):
            raise CommandError("Este diagnóstico somente-leitura exige o ambiente QA normativo isolado.")

        candidates = _archive_retrieval_candidates(
            exact_ref=None,
            explicit_references=[],
            query_tokens=set(),
            required_title="codigo de obras",
        )
        target_candidates = [
            document
            for document in candidates
            if (document.metadata_json or {}).get("identity_candidate", {}).get("number") == "258"
            and (document.metadata_json or {}).get("identity_candidate", {}).get("year") == 2024
            and (document.metadata_json or {}).get("identity_candidate", {}).get("type")
            == "lei_complementar"
        ]
        self.stdout.write(
            json.dumps(
                {
                    "scope": "fixed_code_of_works_transition_qa_scenario",
                    "title_shortlist_count": len(candidates),
                    "target_identity_candidate_count": len(target_candidates),
                    "target_identity_candidates": [
                        _candidate_summary(document) for document in target_candidates
                    ],
                    "natural_query_retrieval": _retrieval_summary(NATURAL_QUERY),
                    "explicit_reference_control": _retrieval_summary(EXPLICIT_QUERY),
                    "legal_text_emitted": False,
                    "writes_performed": False,
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
