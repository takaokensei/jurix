from datetime import date

import pytest
from django.core.exceptions import ValidationError
from django.urls import reverse

from src.apps.legislation.document_models import AIPilotAdoption
from src.apps.legislation.models import Norma


def _norma():
    return Norma.objects.create(tipo="Lei Complementar", numero="258", ano=2024)


@pytest.mark.django_db
def test_ai_adoption_is_explicit_scoped_and_append_only(db):
    adoption = AIPilotAdoption.objects.create(
        case_key=AIPilotAdoption.Case.LC258_REPEALS,
        adopted_on=date(2026, 10, 18),
        review_draft_sha256="a" * 64,
        review_report_sha256="b" * 64,
        source_manifest_sha256="c" * 64,
        norma=_norma(),
        evidence_json={"adopted_items": ["III", "IV", "V", "VI"]},
        limitations_json=["I, II e VII permanecem sem alvo resolvido."],
    )

    assert adoption.decision == "adopted_for_pilot"
    assert adoption.review_kind == "ai_documentary_review"
    assert adoption.adoption_basis == "project_owner_explicit"

    adoption.decision = "consolidated"
    with pytest.raises(ValidationError, match="Adoções são imutáveis"):
        adoption.save()

    with pytest.raises(ValidationError, match="preservadas para auditoria"):
        adoption.delete()


@pytest.mark.django_db
def test_ai_adoption_rejects_empty_scope_and_human_review_claim(db):
    adoption = AIPilotAdoption(
        case_key=AIPilotAdoption.Case.LC208_LC261,
        adopted_on=date(2026, 10, 18),
        review_draft_sha256="a" * 64,
        review_report_sha256="b" * 64,
        source_manifest_sha256="c" * 64,
        norma=_norma(),
        evidence_json={},
        limitations_json=[],
        review_kind="human_approved",
    )

    with pytest.raises(ValidationError) as exc:
        adoption.full_clean()

    assert "review_kind" in exc.value.message_dict
    assert "evidence_json" in exc.value.message_dict
    assert "limitations_json" in exc.value.message_dict


@pytest.mark.django_db
def test_pilot_adoption_page_shows_ai_origin_conflict_and_scoped_evidence(client):
    AIPilotAdoption.objects.create(
        case_key=AIPilotAdoption.Case.LC55_CONFLICT,
        adopted_on=date(2026, 10, 18),
        review_draft_sha256="a" * 64,
        review_report_sha256="b" * 64,
        source_manifest_sha256="c" * 64,
        evidence_json={
            "events": [
                {
                    "relation_key": "C-example",
                    "action": "ADICIONA",
                    "target": {"literal_target": "LC 55/2004, Art. 34, § 3º"},
                    "target_resolution": "documentary_conflict",
                    "documentary_assessment": "A numeração diverge entre as fontes.",
                    "evidence": {
                        "source_id": "F11",
                        "article": "2º",
                        "pages": [1],
                        "quote": "Art. 34, § 3º",
                    },
                }
            ],
            "sources": [
                {
                    "source_id": "F11",
                    "title": "LC 173/2017",
                    "url": "https://sapl.natal.rn.leg.br/norma/1",
                    "pdf_sha256": "d" * 64,
                }
            ],
        },
        limitations_json=["Conflito não resolvido."],
    )

    response = client.get(reverse("workspace:ai_pilot_adoptions"))

    assert response.status_code == 200
    assert b"Conflito preservado" in response.content
    assert b"Revis\xc3\xa3o documental assistida por IA" in response.content
    assert b"A numera\xc3\xa7\xc3\xa3o diverge" in response.content
    assert b"Conflito n\xc3\xa3o resolvido" in response.content
