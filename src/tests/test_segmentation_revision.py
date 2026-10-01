import pytest

from src.apps.legislation.models import Dispositivo, EventoAlteracao, Norma


@pytest.mark.django_db
def test_resegmentation_preserves_device_ids_and_event_references():
    from src.apps.ingestion.segmentation_tasks import segment_text_task

    norma = Norma.objects.create(
        tipo="Lei",
        numero="99001",
        ano=2026,
        texto_original="Art. 1º Primeiro texto.\nArt. 2º Segundo texto.",
    )
    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(
            "src.apps.ingestion.segmentation_tasks._invalidate_rag_cache", lambda: None
        )
        first_result = segment_text_task.run(norma.id)
        assert first_result["success"] is True

        first_devices = {
            row.numero: row for row in Dispositivo.objects.filter(norma=norma, is_active=True)
        }
        referenced = first_devices["2º"]
        event = EventoAlteracao.objects.create(
            dispositivo_fonte=referenced,
            acao="REFERENCIA",
            target_text="Art. 2º",
            referencia_tipo="artigo",
            referencia_numero="2º",
        )

        second_result = segment_text_task.run(norma.id)
        assert second_result["success"] is True

    second_devices = {
        row.numero: row for row in Dispositivo.objects.filter(norma=norma, is_active=True)
    }
    assert {number: row.pk for number, row in first_devices.items()} == {
        number: row.pk for number, row in second_devices.items()
    }
    event.refresh_from_db()
    assert event.dispositivo_fonte_id == referenced.pk
    assert Dispositivo.objects.filter(pk=referenced.pk, is_active=True).exists()


@pytest.mark.django_db
def test_resegmentation_inactivates_removed_device_without_deleting_audit_fk():
    from src.apps.ingestion.segmentation_tasks import segment_text_task

    norma = Norma.objects.create(
        tipo="Lei",
        numero="99002",
        ano=2026,
        texto_original="Art. 1º Primeiro texto.\nArt. 2º Segundo texto.",
    )
    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(
            "src.apps.ingestion.segmentation_tasks._invalidate_rag_cache", lambda: None
        )
        assert segment_text_task.run(norma.id)["success"] is True
        removed = Dispositivo.objects.get(norma=norma, tipo="artigo", numero="2º")
        event = EventoAlteracao.objects.create(
            dispositivo_fonte=removed,
            acao="REFERENCIA",
            target_text="Art. 2º",
            referencia_tipo="artigo",
            referencia_numero="2º",
        )
        norma.texto_original = "Art. 1º Primeiro texto revisto."
        norma.save(update_fields=["texto_original"])
        result = segment_text_task.run(norma.id)

    assert result["success"] is True
    assert result["dispositivos_inactivated"] == 1
    assert Dispositivo.objects.filter(pk=removed.pk, is_active=False).exists()
    event.refresh_from_db()
    assert event.dispositivo_fonte_id == removed.pk
    assert Dispositivo.objects.filter(norma=norma, is_active=True).count() == 1


@pytest.mark.django_db
def test_invalid_new_tree_does_not_delete_previously_segmented_devices(monkeypatch):
    from src.apps.ingestion.segmentation_tasks import segment_text_task

    norma = Norma.objects.create(
        tipo="Lei",
        numero="99003",
        ano=2026,
        texto_original="Art. 1º Texto válido.",
    )
    monkeypatch.setattr("src.apps.ingestion.segmentation_tasks._invalidate_rag_cache", lambda: None)
    assert segment_text_task.run(norma.id)["success"] is True
    original = list(Dispositivo.objects.filter(norma=norma).values_list("pk", flat=True))

    monkeypatch.setattr(
        "src.apps.ingestion.segmentation_tasks.LegalTextParser.build_hierarchy",
        lambda _parser, _elements: [
            {"index": 1, "parent_index": 1, "tipo": "artigo", "numero": "1º", "texto": "x"}
        ],
    )
    result = segment_text_task.run(norma.id)

    assert result["success"] is False
    assert list(Dispositivo.objects.filter(norma=norma).values_list("pk", flat=True)) == original
