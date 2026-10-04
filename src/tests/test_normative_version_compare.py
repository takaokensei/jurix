from datetime import date
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from django.test import Client, override_settings

from src.apps.legislation.models import Dispositivo, Norma
from src.processing.legal_diff import build_version_diff


@pytest.fixture
def norma(db):
    return Norma.objects.create(
        tipo="Lei",
        numero="123",
        ano=2026,
        status="consolidated",
        ementa="Norma de teste",
        texto_original="Art. 1º Texto.",
        texto_consolidado="Lei nº 123/2026\nArt. 1º Texto.",
    )


def _device(key, text, status="in_force", order=1):
    return {
        "structural_key": key,
        "text": text,
        "legal_status": status,
        "order": order,
    }


def test_version_diff_classifies_text_status_and_complete_additions():
    rows = build_version_diff(
        [
            _device("art:1", "Redação antiga"),
            _device("art:2", "Redação que saiu"),
            _device("art:3", "Texto vetado", "vetoed"),
        ],
        [
            _device("art:1", "Redação nova"),
            _device("art:3", "Texto vetado", "in_force"),
            _device("art:4", "Novo dispositivo"),
        ],
        before_complete=True,
        after_complete=True,
    )
    assert [row["kind"] for row in rows] == ["changed", "removed", "vetoed", "added"]
    assert rows[0]["before"] == "Redação antiga"
    assert rows[0]["after"] == "Redação nova"
    assert rows[2]["label"] == "Dispositivo vetado em uma das projeções"


def test_partial_projection_never_interprets_missing_device_as_added_or_removed():
    rows = build_version_diff(
        [_device("art:1", "Texto")],
        [],
        before_complete=True,
        after_complete=False,
    )
    assert rows[0]["kind"] == "coverage_unknown"
    assert "Ausência não conclusiva" in rows[0]["label"]


def test_duplicate_structural_keys_are_rejected():
    with pytest.raises(ValueError, match="structural_key única"):
        build_version_diff(
            [_device("art:1", "Um"), _device("art:1", "Dois")],
            [],
            before_complete=True,
            after_complete=True,
        )


def test_projected_device_label_is_human_readable_not_a_hash():
    device = SimpleNamespace(
        source=SimpleNamespace(structural_key="opaque-stable-hash", tipo="artigo", numero="5º", ordem=1),
        text="Texto legal",
        legal_status="in_force",
    )
    row = build_version_diff(
        [device], [device], before_complete=True, after_complete=True
    )[0]
    assert row["device_label"] == "Art. 5º"
    assert row["structural_key"] == "opaque-stable-hash"


def _projection(when, *, status="complete", devices=()):
    return SimpleNamespace(
        as_of=when,
        status=status,
        devices=tuple(devices),
        coverage={
            "device_count": len(devices),
            "applied_event_ids": [],
            "pending_event_ids": [],
        },
    )


@pytest.mark.django_db
@override_settings(NORMATIVE_HISTORY_ENABLED=True)
def test_temporal_compare_keeps_dates_in_url_and_labels_jurix_projection(norma):
    before = date(2025, 1, 1)
    after = date(2026, 1, 1)
    old = [_device("art:1", "Texto antigo")]
    new = [_device("art:1", "Texto novo")]
    with patch(
        "src.processing.normative_projection.project_norma_as_of",
        side_effect=[_projection(before, devices=old), _projection(after, devices=new)],
    ), patch(
        "src.apps.legislation.views.build_norma_timeline",
        return_value=[
            {
                "kind": "event",
                "date": "2021-03-01",
                "date_display": "01/03/2021",
                "title": "Alteração",
                "description": "Trecho de alteração sintético.",
                "source_norma_id": norma.pk,
                "source_norma": "Lei nº 123/2026",
                "target_dispositivo_id": 99,
                "pending": False,
            }
        ],
    ):
        response = Client().get(
            f"/normas/{norma.pk}/compare/?from_as_of=2025-01-01&to_as_of=2026-01-01"
        )

    body = response.content.decode()
    assert response.status_code == 200
    assert 'value="2025-01-01"' in body
    assert 'value="2026-01-01"' in body
    assert "consolidação histórica do Jurix" in body
    assert "Diferença textual estrutural" in body
    assert "Texto antigo" in body and "Texto novo" in body
    assert "Abrir norma fonte" in body
    assert "Abrir dispositivo relacionado" in body


@pytest.mark.django_db
@override_settings(NORMATIVE_HISTORY_ENABLED=True)
def test_temporal_compare_explains_unavailable_projection_without_latest_fallback(norma):
    missing = _projection(
        date(2025, 1, 1),
        status="not_reconstructable",
    )
    with patch(
        "src.processing.normative_projection.project_norma_as_of",
        side_effect=[missing, _projection(date(2026, 1, 1), devices=[_device("art:1", "Atual")])],
    ):
        response = Client().get(
            f"/normas/{norma.pk}/compare/?from_as_of=2025-01-01&to_as_of=2026-01-01"
        )

    body = response.content.decode()
    assert response.status_code == 200
    assert "não será usado como substituto" in body
    assert "Texto atual" not in body


@pytest.mark.django_db
@override_settings(NORMATIVE_HISTORY_ENABLED=True)
def test_temporal_compare_validates_both_dates_and_order_before_projection(norma):
    with patch("src.processing.normative_projection.project_norma_as_of") as project:
        response = Client().get(f"/normas/{norma.pk}/compare/?from_as_of=2026-02-01")
    assert response.status_code == 200
    assert "Informe as duas datas" in response.content.decode()
    project.assert_not_called()

    with patch("src.processing.normative_projection.project_norma_as_of") as project:
        response = Client().get(
            f"/normas/{norma.pk}/compare/?from_as_of=2026-02-02&to_as_of=2026-02-01"
        )
    assert "anterior ou igual" in response.content.decode()
    project.assert_not_called()


@pytest.mark.django_db
@override_settings(NORMATIVE_HISTORY_ENABLED=True)
def test_legacy_compare_exposes_historical_date_entry_without_projecting(norma):
    with patch("src.processing.normative_projection.project_norma_as_of") as project:
        response = Client().get(f"/normas/{norma.pk}/compare/?history=1")
    body = response.content.decode()
    assert response.status_code == 200
    assert 'name="from_as_of" type="date"' in body
    assert 'name="to_as_of" type="date"' in body
    assert "Comparar datas" in body
    project.assert_not_called()


@pytest.mark.django_db
@override_settings(NORMATIVE_HISTORY_ENABLED=True)
def test_precedent_mode_is_explicit_and_does_not_project_until_decision_date_is_set(norma):
    with patch("src.processing.normative_projection.project_norma_as_of") as project:
        response = Client().get(
            f"/normas/{norma.pk}/compare/?history=1&mode=precedent"
        )
    body = response.content.decode()
    assert response.status_code == 200
    assert "Checar mudanças desde a data de uma decisão" in body
    assert 'name="mode" value="precedent"' in body
    assert 'label for="from-as-of">Data da decisão</label>' in body
    assert "não avalia validade, força vinculante ou aplicabilidade" in body
    assert 'name="to_as_of" type="date" value="' in body
    project.assert_not_called()


@pytest.mark.django_db
@override_settings(NORMATIVE_HISTORY_ENABLED=True)
def test_norma_detail_links_to_precedent_temporal_check(norma):
    device = Dispositivo.objects.create(
        norma=norma,
        tipo="artigo",
        numero="1º",
        ordem=1,
        texto="Texto do dispositivo",
        structural_key="art:1",
    )
    response = Client().get(f"/normas/{norma.pk}/")
    assert response.status_code == 200
    body = response.content.decode()
    assert "Checar alteração desde uma decisão" in body
    assert f"/normas/{norma.pk}/compare/?history=1&amp;mode=precedent" in body
    assert f"mode=precedent&amp;device_id={device.pk}" in body


@pytest.mark.django_db
@override_settings(NORMATIVE_HISTORY_ENABLED=True)
def test_precedent_mode_can_focus_one_device_without_conflating_other_articles(norma):
    selected = Dispositivo.objects.create(
        norma=norma,
        tipo="artigo",
        numero="1º",
        ordem=1,
        texto="Artigo selecionado",
        structural_key="art:1",
    )
    other = Dispositivo.objects.create(
        norma=norma,
        tipo="artigo",
        numero="2º",
        ordem=2,
        texto="Outro artigo",
        structural_key="art:2",
    )
    before_devices = [
        SimpleNamespace(source=selected, text="Redação antiga", legal_status="in_force"),
        SimpleNamespace(source=other, text="Outro texto antigo", legal_status="in_force"),
    ]
    after_devices = [
        SimpleNamespace(source=selected, text="Redação nova", legal_status="in_force"),
        SimpleNamespace(source=other, text="Outro texto atual", legal_status="in_force"),
    ]
    with patch(
        "src.processing.normative_projection.project_norma_as_of",
        side_effect=[
            _projection(date(2025, 1, 1), devices=before_devices),
            _projection(date(2026, 1, 1), devices=after_devices),
        ],
    ), patch("src.apps.legislation.views.build_norma_timeline", return_value=[]):
        response = Client().get(
            f"/normas/{norma.pk}/compare/?history=1&mode=precedent&device_id={selected.pk}"
            "&from_as_of=2025-01-01&to_as_of=2026-01-01"
        )

    body = response.content.decode()
    assert response.status_code == 200
    assert "Dispositivo em foco" in body
    assert "Art. 1º" in body
    assert "Redação antiga" in body and "Redação nova" in body
    assert "Outro texto antigo" not in body and "Outro texto atual" not in body


@pytest.mark.django_db
@override_settings(NORMATIVE_HISTORY_ENABLED=False)
def test_temporal_compare_feature_off_does_not_call_projection(norma):
    with patch("src.processing.normative_projection.project_norma_as_of") as project:
        response = Client().get(
            f"/normas/{norma.pk}/compare/?from_as_of=2025-01-01&to_as_of=2026-01-01"
        )
    body = response.content.decode()
    assert response.status_code == 200
    assert "indisponível nesta instalação" in body
    assert "Texto consolidado atual" not in body
    project.assert_not_called()
