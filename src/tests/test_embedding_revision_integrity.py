from datetime import UTC, datetime
from unittest.mock import patch

import pytest

from src.apps.legislation.models import Dispositivo, Norma
from src.processing.device_revision import revision_fingerprint


@pytest.mark.django_db
def test_segmentation_revision_change_invalidates_vector_metadata(monkeypatch):
    from src.apps.ingestion.segmentation_tasks import segment_text_task

    norma = Norma.objects.create(
        tipo="Lei", numero="99201", ano=2026, texto_original="Art. 1º Texto inicial."
    )
    monkeypatch.setattr("src.apps.ingestion.segmentation_tasks._invalidate_rag_cache", lambda: None)
    assert segment_text_task.run(norma.pk)["success"] is True
    device = Dispositivo.objects.get(norma=norma)
    device.embedding_model = "nomic-embed-text"
    device.embedding_generated_at = datetime.now(UTC)
    device.embedding_revision_fingerprint = device.revision_fingerprint
    device.save(
        update_fields=[
            "embedding_model",
            "embedding_generated_at",
            "embedding_revision_fingerprint",
        ]
    )

    norma.texto_original = "Art. 1º Texto alterado."
    norma.save(update_fields=["texto_original"])
    assert segment_text_task.run(norma.pk)["success"] is True

    device.refresh_from_db()
    assert device.revision_fingerprint == revision_fingerprint(device.texto, device.texto_bruto)
    assert device.embedding_model == ""
    assert device.embedding_generated_at is None
    assert device.embedding_revision_fingerprint == ""


@pytest.mark.django_db
def test_embedding_result_is_discarded_when_source_changes_mid_generation(monkeypatch):
    from src.apps.ingestion.ner_tasks import generate_embedding_task

    norma = Norma.objects.create(tipo="Lei", numero="99202", ano=2026)
    text = "Texto original com extensão suficiente para não ser ignorado."
    device = Dispositivo.objects.create(
        norma=norma,
        tipo="artigo",
        numero="1º",
        texto=text,
        texto_bruto=text,
        ordem=1,
        revision_fingerprint=revision_fingerprint(text, text),
    )

    def generate_then_mutate(_self, *_args, **_kwargs):
        current = Dispositivo.objects.get(pk=device.pk)
        current.texto = "Nova revisão que chegou enquanto o embedding era calculado."
        current.texto_bruto = current.texto
        current.revision_fingerprint = revision_fingerprint(current.texto, current.texto_bruto)
        current.save(update_fields=["texto", "texto_bruto", "revision_fingerprint"])
        return [0.1] * 768

    monkeypatch.setattr("src.apps.ingestion.ner_tasks.OllamaService.check_health", lambda *_: True)
    monkeypatch.setattr(
        "src.apps.ingestion.ner_tasks.OllamaService.generate_embedding", generate_then_mutate
    )
    with patch(
        "src.apps.ingestion.ner_tasks._persist_embedding_if_current", return_value=False
    ) as persist:
        result = generate_embedding_task.run(device.pk)

    persist.assert_called_once()
    assert (
        persist.call_args.kwargs["source_revision"]
        != Dispositivo.objects.get(pk=device.pk).revision_fingerprint
    )

    assert result["success"] is False
    assert result["stale_input"] is True
