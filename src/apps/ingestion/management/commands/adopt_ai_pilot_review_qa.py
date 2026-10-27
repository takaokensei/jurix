"""Import the explicitly adopted, hash-pinned documentary review into isolated QA."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import date
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from src.apps.legislation.document_models import AIPilotAdoption
from src.apps.legislation.models import Norma

EXPECTED_DRAFT_SHA256 = "667d20e090ffdb9808ff2adebe6e02f614c5326091b14f659a87449e25198db9"
EXPECTED_REPORT_SHA256 = "3fe1a49bca30c4f76ede71bf75842c580a06aeea8849b1f87f4ab79c2d70722e"
EXPECTED_SOURCES_SHA256 = "8db2c6530e3f768cbf96c9784b2bed322b2deb89f907a56429c6070e1eadc451"
EXPECTED_SPANS_SHA256 = "32ef095a3e4b52b83afcceb3426854d31e0ccbc081e7daa0b2bf7163b0029b57"

CASE_SPECS = {
    "A": {
        "case_key": AIPilotAdoption.Case.CTM_ART20,
        "relation_keys": {"A-271-1-CTM20"},
        "sapl_id": None,
        "limitations": [
            "Somente o Art. 20 e o ato modificador foram cotejados integralmente.",
            "A data observada no DOM e a divergência do colofão SAPL permanecem distintas.",
            "Não certifica vigência atual do CTM nem efeitos tributários completos.",
        ],
    },
    "B": {
        "case_key": AIPilotAdoption.Case.LC258_REPEALS,
        "relation_keys": {
            "B-258-260-III", "B-258-260-IV", "B-258-260-V", "B-258-260-VI"
        },
        "sapl_id": 4052,
        "limitations": [
            "Somente os incisos III, IV, V e VI foram adotados para o piloto.",
            "Os incisos I, II e VII permanecem com alvo não resolvido.",
            "O inciso V atinge apenas o Art. 21 da LP 275/2009.",
            "A transição não decide automaticamente processos administrativos reais.",
        ],
    },
    "C": {
        "case_key": AIPilotAdoption.Case.LC55_CONFLICT,
        "relation_keys": {
            "C-173-2-LC55-par3", "C-173-2-LC55-par4", "C-185-87-LC55-par3"
        },
        "sapl_id": None,
        "limitations": [
            "Adotado apenas como caso demonstrativo de divergência documental.",
            "A numeração conflitante do Art. 34 não foi resolvida nem renumerada.",
            "Não apresentar uma redação única como reconstruída para qualquer data.",
        ],
    },
    "D": {
        "case_key": AIPilotAdoption.Case.LC208_LC261,
        "relation_keys": {"D-261-118-LC208-par2"},
        "sapl_id": 1160,
        "limitations": [
            "Adotado somente o cotejo textual do Art. 18, § 2º, com LC 261, Art. 118.",
            "A associação cadastral pendente e a data de efeitos continuam sem confirmação.",
            "Não declara que todos os atos posteriores foram examinados.",
        ],
    },
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class Command(BaseCommand):
    help = "Importa no QA isolado a adoção explícita da revisão documental por IA."

    def add_arguments(self, parser):
        parser.add_argument("--package-root", required=True)

    def handle(self, *args, **options):
        if os.environ.get("JURIX_QA_ONLY") != "1":
            raise CommandError("Este comando só pode ser executado com JURIX_QA_ONLY=1.")
        package_root = Path(options["package_root"]).resolve()
        draft_path = package_root.parent / "review-draft.json"
        report_path = package_root.parent / "REVISAO_DOCUMENTAL_JURIX.md"
        sources_path = package_root / "sources.json"
        spans_path = package_root / "spans.json"
        expected = (
            (draft_path, EXPECTED_DRAFT_SHA256),
            (report_path, EXPECTED_REPORT_SHA256),
            (sources_path, EXPECTED_SOURCES_SHA256),
            (spans_path, EXPECTED_SPANS_SHA256),
        )
        for path, digest in expected:
            if not path.is_file() or _sha256(path) != digest:
                raise CommandError(f"Pacote ausente ou hash divergente: {path.name}.")

        draft = json.loads(draft_path.read_text(encoding="utf-8"))
        sources = json.loads(sources_path.read_text(encoding="utf-8"))
        if (
            draft.get("format") != "jurix_document_review_draft_v1"
            or draft.get("status") != "candidate"
            or draft.get("human_approved") is not False
        ):
            raise CommandError("A minuta não corresponde ao esquema candidato esperado.")

        source_by_id = {row["source_id"]: row for row in sources}
        events_by_case = {}
        for event in draft.get("events", []):
            events_by_case.setdefault(event.get("case"), []).append(event)
        report_sha = _sha256(report_path)
        draft_sha = _sha256(draft_path)
        manifest_sha = hashlib.sha256(
            (EXPECTED_SOURCES_SHA256 + EXPECTED_SPANS_SHA256).encode("ascii")
        ).hexdigest()

        created = 0
        existing = 0
        with transaction.atomic():
            for case, spec in CASE_SPECS.items():
                events = [
                    row for row in events_by_case.get(case, [])
                    if row.get("relation_key") in spec["relation_keys"]
                ]
                if {row.get("relation_key") for row in events} != spec["relation_keys"]:
                    raise CommandError(f"Escopo documental inesperado para o caso {case}.")
                evidence_sources = set()
                for event in events:
                    evidence = event.get("evidence") or {}
                    source_id = evidence.get("source_id")
                    if source_id not in source_by_id:
                        raise CommandError(f"Fonte não congelada no caso {case}.")
                    evidence_sources.add(source_id)
                    source = source_by_id[source_id]
                    frozen_path = package_root / f"{source_id}.frozen.txt"
                    if not frozen_path.is_file():
                        raise CommandError(f"Texto congelado ausente para {source_id}.")
                    frozen_text = frozen_path.read_text(encoding="utf-8")
                    start, end = evidence.get("start"), evidence.get("end")
                    quote = evidence.get("quote")
                    if (
                        not isinstance(start, int)
                        or not isinstance(end, int)
                        or frozen_text[start:end] != quote
                        or hashlib.sha256(frozen_text.encode("utf-8")).hexdigest()
                        != source.get("text_sha256")
                        or evidence.get("text_sha256") != source.get("text_sha256")
                    ):
                        raise CommandError(f"Recorte/hash divergente no caso {case}.")
                case_sources = [
                    source_by_id[key] for key in sorted(evidence_sources)
                ]
                payload = {
                    "schema": "jurix-ai-pilot-adoption-v1",
                    "source_kind": "ai_documentary_review",
                    "events": events,
                    "sources": case_sources,
                    "review_status_at_adoption": "candidate_not_human_approved",
                }
                norm = None
                if spec["sapl_id"]:
                    norm = Norma.objects.filter(sapl_id=spec["sapl_id"]).first()
                values = {
                    "adopted_on": date.fromisoformat(draft["as_of"]),
                    "review_draft_sha256": draft_sha,
                    "review_report_sha256": report_sha,
                    "source_manifest_sha256": manifest_sha,
                    "norma": norm,
                    "evidence_json": payload,
                    "limitations_json": spec["limitations"],
                }
                row = AIPilotAdoption.objects.filter(
                    case_key=spec["case_key"], revision=1
                ).first()
                if row:
                    if any(getattr(row, key) != value for key, value in values.items()):
                        raise CommandError(
                            f"Adoção existente diverge para {case}; nenhuma linha será substituída."
                        )
                    existing += 1
                    continue
                AIPilotAdoption.objects.create(
                    case_key=spec["case_key"], revision=1, **values
                )
                created += 1
        self.stdout.write(
            self.style.SUCCESS(f"Adoções QA criadas: {created}; já existentes: {existing}.")
        )
