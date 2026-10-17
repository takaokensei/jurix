from types import SimpleNamespace

import pytest

from src.apps.ingestion.task_support import _resolve_norma_reference
from src.apps.legislation.models import Dispositivo, EventoAlteracao, Norma
from src.processing.document_metadata import build_normative_identity
from src.processing.target_reconciliation import (
    parse_target_reference,
    reconcile_unresolved_event_targets,
    resolve_event_target,
)


def test_parse_target_reference_from_target_text():
    event = SimpleNamespace(
        referencia_tipo=None,
        referencia_numero=None,
        target_text="altera a Lei nº 8.206/2026",
        norma=SimpleNamespace(ano=2026),
    )
    ref = parse_target_reference(event)
    assert ref is not None
    assert ref.numero == "8.206"
    assert ref.ano == 2026


def test_parse_target_reference_accepts_full_civil_date_after_norm_number():
    event = SimpleNamespace(
        target_text=(
            "Art. 14 da Lei Complementar nº 208, de 7 de março de 2022"
        )
    )

    ref = parse_target_reference(event)

    assert ref is not None
    assert ref.type_key == "lei_complementar"
    assert ref.number_key == "208"
    assert ref.ano == 2022


def test_parse_target_reference_uses_exact_evidence_for_article_only_target():
    event = SimpleNamespace(
        target_text="Art. 14",
        evidence_json={
            "target_quote": (
                "Art. 14 da Lei Complementar nº 208, de 7 de março de 2022"
            )
        },
        target_reference_json={"resolution_status": "candidate"},
    )

    reference = parse_target_reference(event)

    assert reference is not None
    assert reference.type_key == "lei_complementar"
    assert reference.number_key == "208"
    assert reference.ano == 2022


def test_parse_target_reference_uses_explicit_structured_ner_candidate():
    event = SimpleNamespace(
        target_text="Art. 14",
        evidence_json={},
        target_reference_json={
            "kind": "normative_reference",
            "type_candidate": "lei_complementar",
            "number_candidate": "208,",
            "year_candidate": "2022",
            "resolution_status": "candidate",
        },
    )

    reference = parse_target_reference(event)

    assert reference is not None
    assert reference.type_key == "lei_complementar"
    assert reference.number_key == "208"
    assert reference.ano == 2022


@pytest.mark.parametrize("status", ["ambiguous_multiple_normas", "unresolved_or_ambiguous_reference"])
def test_parse_target_reference_does_not_promote_ambiguous_structured_candidate(status):
    event = SimpleNamespace(
        target_text="Art. 14",
        evidence_json={},
        target_reference_json={
            "type_candidate": "lei_complementar",
            "number_candidate": "208",
            "year_candidate": "2022",
            "resolution_status": status,
        },
    )

    assert parse_target_reference(event) is None


def test_yearless_structured_reference_does_not_inherit_altering_norm_year():
    event = SimpleNamespace(
        referencia_tipo="Lei",
        referencia_numero="8206",
        target_text="Lei nº 8206",
        norma=SimpleNamespace(ano=2026),
    )
    assert parse_target_reference(event) is None


def test_yearless_target_text_is_not_parsed_as_a_confirmed_reference():
    event = SimpleNamespace(
        referencia_tipo=None,
        referencia_numero=None,
        target_text="altera a Lei nº 8.206",
        norma=SimpleNamespace(ano=2026),
    )
    assert parse_target_reference(event) is None


@pytest.mark.parametrize(
    "text,expected_scope",
    [
        ("Lei nº 8.206/2026", "unknown"),
        ("Lei Municipal nº 8.206/2026", "municipal"),
        ("Lei Federal nº 8.206/2026", "federal"),
    ],
)
def test_parse_target_reference_preserves_explicit_scope(text, expected_scope):
    event = SimpleNamespace(target_text=text)
    reference = parse_target_reference(event)
    assert reference is not None
    assert reference.ano == 2026
    assert reference.jurisdiction == expected_scope


@pytest.mark.django_db
def test_reconcile_never_links_explicit_federal_reference_to_same_number_municipal_norma():
    source = Norma.objects.create(tipo="Lei", numero="1", ano=2026)
    device = Dispositivo.objects.create(norma=source, tipo="artigo", numero="1", ordem=1)
    target = Norma.objects.create(tipo="Lei", numero="4320", ano=1964)
    event = EventoAlteracao.objects.create(
        dispositivo_fonte=device,
        acao="REFERENCIA",
        target_text="Lei Federal nº 4.320/1964",
        validado=False,
    )

    assert resolve_event_target(event) is False
    event.refresh_from_db()
    assert event.norma_alvo_id is None
    assert event.validado is False
    assert event.target_reference_json["resolution_status"] == "external_jurisdiction"
    assert event.target_reference_json["external_identity_key"] == "FEDERAL|lei|4320|1964"
    assert target.pk != event.norma_alvo_id


@pytest.mark.django_db
def test_reconcile_distinguishes_law_from_complementary_law_and_normalizes_leading_zeroes():
    source = Norma.objects.create(tipo="Lei", numero="1", ano=2026)
    device = Dispositivo.objects.create(norma=source, tipo="artigo", numero="1", ordem=1)
    ordinary = Norma.objects.create(tipo="Lei", numero="55", ano=2020)
    complementary = Norma.objects.create(tipo="Lei Complementar", numero="55", ano=2020)
    event = EventoAlteracao.objects.create(
        dispositivo_fonte=device,
        acao="REFERENCIA",
        target_text="Lei Complementar nº 0055/2020",
    )

    assert resolve_event_target(event) is True
    event.refresh_from_db()
    assert event.norma_alvo_id == complementary.pk
    assert event.norma_alvo_id != ordinary.pk
    assert event.target_reference_json["match_method"] == "unique_legacy_type_number_year"
    assert event.validado is False


@pytest.mark.django_db
def test_second_pass_resolves_article_only_display_using_target_evidence_span():
    source = Norma.objects.create(tipo="Lei Complementar", numero="258", ano=2024)
    device = Dispositivo.objects.create(norma=source, tipo="artigo", numero="261", ordem=261)
    target = Norma.objects.create(tipo="Lei Complementar", numero="208", ano=2022)
    event = EventoAlteracao.objects.create(
        dispositivo_fonte=device,
        acao="ALTERA",
        target_text="Art. 14",
        referencia_tipo="artigo",
        referencia_numero="14",
        evidence_json={
            "target_quote": (
                "Art. 14 da Lei Complementar nº 208, de 7 de março de 2022"
            )
        },
        target_reference_json={
            "kind": "normative_reference",
            "type_candidate": "Lei Complementar",
            "number_candidate": "208,",
            "year_candidate": 2022,
            "resolution_status": "candidate",
        },
        validado=False,
    )

    assert resolve_event_target(event) is True

    event.refresh_from_db()
    assert event.norma_alvo_id == target.pk
    assert event.dispositivo_alvo_id is None
    assert event.validado is False
    assert event.target_reference_json["resolution_status"] == "resolved_unreviewed"


@pytest.mark.django_db
def test_duplicate_legacy_matches_stay_unresolved_and_report_ambiguity():
    source = Norma.objects.create(tipo="Lei", numero="1", ano=2026)
    device = Dispositivo.objects.create(norma=source, tipo="artigo", numero="1", ordem=1)
    Norma.objects.create(tipo="Lei Ordinária", numero="70", ano=2020)
    Norma.objects.create(tipo="Lei", numero="070", ano=2020)
    event = EventoAlteracao.objects.create(
        dispositivo_fonte=device,
        acao="ALTERA",
        target_text="Lei nº 70/2020",
    )

    assert resolve_event_target(event) is False
    event.refresh_from_db()
    assert event.norma_alvo_id is None
    assert event.target_reference_json["resolution_status"] == "ambiguous_multiple_candidates"


@pytest.mark.django_db
def test_second_pass_links_late_arriving_target_only_in_requested_scope():
    source = Norma.objects.create(tipo="Lei", numero="1", ano=2026)
    device = Dispositivo.objects.create(norma=source, tipo="artigo", numero="1", ordem=1)
    event = EventoAlteracao.objects.create(
        dispositivo_fonte=device,
        acao="ALTERA",
        target_text="Lei nº 8206/2020",
    )
    other = EventoAlteracao.objects.create(
        dispositivo_fonte=device,
        acao="ALTERA",
        target_text="Lei nº 9999/2020",
    )
    target = Norma.objects.create(tipo="Lei", numero="8206", ano=2020)

    stats = reconcile_unresolved_event_targets(target_norma_ids=[target.pk], limit=1)
    event.refresh_from_db()
    other.refresh_from_db()
    assert stats == {"inspected": 1, "resolved": 1, "remaining_unresolved": 0}
    assert event.norma_alvo_id == target.pk
    assert other.norma_alvo_id is None
    assert event.validado is False


@pytest.mark.django_db
def test_explicit_municipal_reference_prefers_confirmed_identity_key():
    source = Norma.objects.create(tipo="Lei", numero="1", ano=2026)
    device = Dispositivo.objects.create(norma=source, tipo="artigo", numero="1", ordem=1)
    identity = build_normative_identity(
        jurisdiction="Município de Natal",
        raw_type="Lei",
        series="municipal_lo",
        number="008206",
        year=2020,
    )
    target = Norma.objects.create(
        tipo="Lei",
        numero="8206",
        ano=2020,
        identity_key=identity.identity_key,
        identity_json=identity.identity_json,
    )
    event = EventoAlteracao.objects.create(
        dispositivo_fonte=device,
        acao="ALTERA",
        target_text="Lei Municipal nº 8.206/2020",
    )

    assert resolve_event_target(event) is True
    event.refresh_from_db()
    assert event.norma_alvo_id == target.pk
    assert event.target_reference_json["match_method"] == "identity_key"


@pytest.mark.django_db
def test_explicit_municipal_reference_accepts_canonical_natal_identity_but_not_other_scope():
    source = Norma.objects.create(tipo="Lei", numero="1", ano=2026)
    device = Dispositivo.objects.create(norma=source, tipo="artigo", numero="1", ordem=1)
    identity = build_normative_identity(
        jurisdiction="BR-RN-NATAL",
        raw_type="Lei",
        series="municipal_lo",
        number="98206",
        year=2020,
    )
    target = Norma.objects.create(
        tipo="Lei", numero="98206", ano=2020,
        identity_key=identity.identity_key, identity_json=identity.identity_json,
    )
    event = EventoAlteracao.objects.create(
        dispositivo_fonte=device,
        acao="ALTERA",
        target_text="Lei Municipal nº 98.206/2020",
    )

    assert resolve_event_target(event) is True
    event.refresh_from_db()
    assert event.norma_alvo_id == target.pk


@pytest.mark.django_db
def test_ingestion_reference_resolver_requires_a_unique_canonical_match():
    ordinary = Norma.objects.create(tipo="Lei Ordinária", numero="008206", ano=2020)
    complementary = Norma.objects.create(tipo="Lei Complementar", numero="8206", ano=2020)

    assert _resolve_norma_reference("Lei", "8.206", "2020") == ordinary
    assert _resolve_norma_reference("Lei Complementar", "8206", "2020") == complementary
    Norma.objects.create(tipo="Lei", numero="8206", ano=2020)
    assert _resolve_norma_reference("Lei", "8206", "2020") is None
