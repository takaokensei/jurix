import re
from datetime import date
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from django.test import Client, override_settings
from django.urls import reverse

from src.apps.legislation.models import Dispositivo, Norma
from src.processing.evidence_export import build_evidence_package
from src.processing.legal_diff import build_version_diff
from src.processing.normative_casefile import _casefile_digest, build_normative_casefile


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


def test_casefile_digest_tracks_content_and_ignores_generation_time():
    as_of = date(2026, 10, 17)
    projection = SimpleNamespace(
        status="complete",
        input_sha256="input-v1",
        content_sha256="content-v1",
    )
    graph = {
        "scope": "reviewed_normative_relation",
        "nodes": [{"id": "norma:1", "label": "Lei 1"}],
        "edges": [{"id": "event:1", "action": "amends"}],
        "truncated": False,
        "filters": {},
    }
    evidence = {
        "schema_version": "jurix-evidence-v1",
        "generated_at": "2026-10-17T10:00:00Z",
        "corpus_coverage": {"complete": True},
        "sources": [{"id": "source:1", "excerpt": "Art. 1º"}],
    }
    kwargs = {
        "corpus_revision": {"revision": 4, "digest": "corpus-v1"},
        "projection": projection,
        "graph": graph,
        "evidence_package": evidence,
    }
    baseline = _casefile_digest(1, as_of, **kwargs)

    timestamp_only = {**evidence, "generated_at": "2026-10-17T11:00:00Z"}
    assert _casefile_digest(
        1, as_of, **{**kwargs, "evidence_package": timestamp_only}
    ) == baseline

    changed_projection = SimpleNamespace(
        status="complete",
        input_sha256="input-v1",
        content_sha256="content-v2",
    )
    assert _casefile_digest(
        1, as_of, **{**kwargs, "projection": changed_projection}
    ) != baseline

    changed_graph = {**graph, "edges": [{"id": "event:2", "action": "repeals"}]}
    assert _casefile_digest(1, as_of, **{**kwargs, "graph": changed_graph}) != baseline

    changed_evidence = {
        **evidence,
        "sources": [{"id": "source:1", "excerpt": "Art. 1º alterado"}],
    }
    assert _casefile_digest(
        1, as_of, **{**kwargs, "evidence_package": changed_evidence}
    ) != baseline


@pytest.mark.django_db
def test_casefile_id_is_shared_by_graph_and_exported_relation_evidence(norma):
    target = Norma.objects.create(
        tipo="Lei",
        numero="124",
        ano=2026,
        status="consolidated",
        texto_original="",
        texto_consolidado="",
    )
    graph = {
        "scope": "reviewed_normative_relation",
        "nodes": [
            {"id": f"norma:{norma.pk}", "label": str(norma)},
            {"id": f"norma:{target.pk}", "label": str(target)},
        ],
        "edges": [
            {
                "id": "event:casefile-integration",
                "source": f"norma:{norma.pk}",
                "target": f"norma:{target.pk}",
                "action": "ALTERA",
                "review_status": "confirmed",
                "effective_status": "confirmed",
                "source_device_key": "a" * 64,
                "target_device_key": "b" * 64,
                "evidence": {"quote": "dá nova redação ao Art. 1º"},
            }
        ],
        "truncated": False,
        "filters": {},
    }

    with (
        patch("src.processing.normative_casefile.build_normative_graph", return_value=graph),
        patch(
            "src.processing.normative_casefile.get_corpus_revision",
            return_value={"revision": 7, "digest": "c" * 64},
        ),
    ):
        casefile = build_normative_casefile(
            norma,
            as_of=date(2026, 10, 18),
            include_projection=False,
        )

    casefile_id = casefile["casefile_id"]
    graph_edge = casefile["graph"]["edges"][0]
    exported_relation = casefile["evidence_package"]["sources"][0]["graph_relation"]
    assert graph_edge["casefile_id"] == casefile_id
    assert exported_relation["casefile_id"] == casefile_id
    assert exported_relation["event_id"] == graph_edge["id"]

    exported = build_evidence_package(casefile["evidence_package"]["sources"])
    assert exported["sources"][0]["graph_relation"]["casefile_id"] == casefile_id


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


def _casefile(projection):
    return {
        "projection": projection,
        "graph": {"nodes": [], "edges": []},
        "evidence_package": {"sources": [], "schema_version": "jurix-evidence-v1"},
        "casefile_id": "qa-casefile",
    }


@pytest.mark.django_db
@override_settings(NORMATIVE_HISTORY_ENABLED=True)
def test_temporal_compare_keeps_dates_in_url_and_labels_jurix_projection(norma):
    before = date(2025, 1, 1)
    after = date(2026, 1, 1)
    old = [_device("art:1", "Texto antigo")]
    new = [_device("art:1", "Texto novo")]
    with patch(
        "src.processing.normative_casefile.build_normative_casefile",
        side_effect=[
            _casefile(_projection(before, devices=old)),
            _casefile(_projection(after, devices=new)),
        ],
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
        ), patch(
            "src.apps.legislation.views.current_corpus_coverage",
            return_value={
                "coverage_status": "partial",
                "checked_until": None,
                "pending_review": 6664,
                "scope_limited": True,
            },
    ):
        response = Client().get(
            f"/normas/{norma.pk}/compare/?from_as_of=2025-01-01&to_as_of=2026-01-01"
        )

    body = response.content.decode()
    assert response.status_code == 200
    assert 'value="2025-01-01"' in body
    assert 'value="2026-01-01"' in body
    assert "consolidação histórica do Jurix" in body
    assert "Cobertura do corpus: parcial" in body
    assert "6.664 PDFs candidatos aguardam revisão" in body
    assert "Data de corte não informada" in body
    assert "não confirma que toda a legislação municipal foi verificada" in body
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
        "src.processing.normative_casefile.build_normative_casefile",
        side_effect=[
            _casefile(missing),
            _casefile(_projection(date(2026, 1, 1), devices=[_device("art:1", "Atual")])),
        ],
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
        "src.processing.normative_casefile.build_normative_casefile",
        side_effect=[
            _casefile(_projection(date(2025, 1, 1), devices=before_devices)),
            _casefile(_projection(date(2026, 1, 1), devices=after_devices)),
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
@override_settings(NORMATIVE_HISTORY_ENABLED=True, NORMATIVE_GRAPH_ENABLED=True)
def test_generic_normative_casefile_renders_sections_without_latest_text_fallback(norma):
    response = Client().get(
        reverse("workspace:normative_casefile", args=[norma.pk]),
        {"as_of": "2025-01-01"},
    )

    body = response.content.decode()
    assert response.status_code == 200
    assert 'id="casefile-summary-title"' in body
    assert 'data-casefile-tabs' in body
    assert 'aria-label="Seções do dossiê"' in body
    assert 'id="texto-na-data"' in body
    assert 'id="alteracoes"' in body
    assert 'id="grafo"' in body
    assert 'id="fontes"' in body
    assert "Dispositivos cobertos" in body
    assert "Evidências rastreáveis" in body
    assert "Não há texto histórico reconstruível com segurança para esta data." in body
    assert norma.texto_consolidado not in body


@pytest.mark.django_db
@override_settings(NORMATIVE_HISTORY_ENABLED=True, NORMATIVE_GRAPH_ENABLED=True)
def test_two_normas_use_the_same_generic_casefile_route_and_schema(norma):
    second_norma = Norma.objects.create(
        tipo="Lei Complementar",
        numero="456",
        ano=2025,
        status="consolidated",
        ementa="Outra norma de teste",
        texto_original="Art. 1º Outro texto.",
        texto_consolidado="Lei Complementar nº 456/2025\nArt. 1º Outro texto.",
    )
    client = Client()
    responses = [
        client.get(
            reverse("workspace:normative_casefile", args=[selected.pk]),
            {"as_of": "2025-01-01"},
        )
        for selected in (norma, second_norma)
    ]

    assert [response.status_code for response in responses] == [200, 200]
    bodies = [response.content.decode() for response in responses]
    for body in bodies:
        assert 'data-casefile-tabs' in body
        assert 'aria-label="Seções do dossiê"' in body
        assert 'id="texto-na-data"' in body
        assert 'id="alteracoes"' in body
        assert 'id="grafo"' in body
        assert 'id="fontes"' in body
    casefile_ids = [
        re.search(r"Identificador do dossiê: <code>([a-f0-9]{64})</code>", body).group(1)
        for body in bodies
    ]
    assert casefile_ids[0] != casefile_ids[1]


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
