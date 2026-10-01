from unittest.mock import patch

import pytest

from src.apps.legislation.models import Dispositivo, EventoAlteracao, Norma
from src.processing.device_revision import revision_fingerprint


def _create_source(text="Fica alterado o art. 1º desta Lei."):
    norma = Norma.objects.create(tipo="Lei", numero="99101", ano=2026, status="segmented")
    device = Dispositivo.objects.create(
        norma=norma,
        tipo="artigo",
        numero="3º",
        texto=text,
        texto_bruto=text,
        ordem=1,
        structural_key="source-3",
        revision_fingerprint=revision_fingerprint(text, text),
    )
    return norma, device


def _event_payload(*, target="Art. 1º", action="ALTERA"):
    return {
        "acao": action,
        "target_text": target,
        "referencia_tipo": "artigo",
        "referencia_numero": "1º",
        "extraction_confidence": 0.9,
        "extraction_method": "regex",
    }


@pytest.mark.django_db
def test_identical_reextraction_preserves_event_id_and_manual_validation():
    from src.apps.ingestion.ner_tasks import extract_entities_task

    norma, device = _create_source()
    with patch(
        "src.apps.ingestion.ner_tasks.LegalNERExtractor.extract_events",
        return_value=[_event_payload()],
    ):
        first = extract_entities_task.run(norma.pk)
    assert first["success"] is True
    event = EventoAlteracao.objects.get(dispositivo_fonte=device, is_active=True)
    event.validado = True
    event.save(update_fields=["validado"])

    with patch(
        "src.apps.ingestion.ner_tasks.LegalNERExtractor.extract_events",
        return_value=[_event_payload()],
    ):
        second = extract_entities_task.run(norma.pk)

    assert second["success"] is True
    assert second["events_preserved"] == 1
    assert EventoAlteracao.objects.filter(pk=event.pk, is_active=True, validado=True).exists()
    assert EventoAlteracao.objects.filter(dispositivo_fonte=device).count() == 1


@pytest.mark.django_db
def test_changed_evidence_creates_pending_revision_and_keeps_old_event_auditable():
    from src.apps.ingestion.ner_tasks import extract_entities_task

    norma, device = _create_source()
    with patch(
        "src.apps.ingestion.ner_tasks.LegalNERExtractor.extract_events",
        return_value=[_event_payload()],
    ):
        assert extract_entities_task.run(norma.pk)["success"] is True
    old = EventoAlteracao.objects.get(dispositivo_fonte=device, is_active=True)
    old.validado = True
    old.save(update_fields=["validado"])

    device.texto = "Fica revogado o art. 1º desta Lei."
    device.texto_bruto = device.texto
    device.revision_fingerprint = revision_fingerprint(device.texto, device.texto_bruto)
    device.save(update_fields=["texto", "texto_bruto", "revision_fingerprint"])
    with patch(
        "src.apps.ingestion.ner_tasks.LegalNERExtractor.extract_events",
        return_value=[_event_payload(action="REVOGA")],
    ):
        result = extract_entities_task.run(norma.pk)

    assert result["success"] is True
    assert result["events_created"] == 1
    old.refresh_from_db()
    assert old.is_active is False
    assert old.validado is True
    current = EventoAlteracao.objects.get(dispositivo_fonte=device, is_active=True)
    assert current.acao == "REVOGA"
    assert current.validado is False
    assert current.revision_fingerprint != old.revision_fingerprint


@pytest.mark.django_db
def test_empty_reextraction_inactivates_instead_of_deleting_events():
    from src.apps.ingestion.ner_tasks import extract_entities_task

    norma, device = _create_source()
    with patch(
        "src.apps.ingestion.ner_tasks.LegalNERExtractor.extract_events",
        return_value=[_event_payload()],
    ):
        assert extract_entities_task.run(norma.pk)["success"] is True
    event = EventoAlteracao.objects.get(dispositivo_fonte=device)

    with patch("src.apps.ingestion.ner_tasks.LegalNERExtractor.extract_events", return_value=[]):
        result = extract_entities_task.run(norma.pk)

    assert result["success"] is True
    event.refresh_from_db()
    assert event.is_active is False
    assert EventoAlteracao.objects.filter(pk=event.pk).exists()
