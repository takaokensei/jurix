"""Immutable, owner-scoped snapshots saved in a legal research collection."""

import hashlib
import uuid
from datetime import date
from types import SimpleNamespace

import pytest
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.test import Client

from src.apps.legislation.document_models import (
    DocumentoDispositivo,
    DocumentoNormativo,
    ExtracaoDocumento,
    NormativeSnapshot,
    SnapshotDispositivo,
)
from src.apps.legislation.models import Collection, CollectionEvidenceVersion, Dispositivo, Norma
from src.processing import collection_evidence
from src.processing.device_revision import structural_key

pytestmark = pytest.mark.django_db


def _save_projection(
    monkeypatch, *, status, content_hashes, input_hashes=None, devices_by_projection=None
):
    values = iter(content_hashes)
    inputs = iter(input_hashes if input_hashes is not None else content_hashes)
    device_sets = iter(devices_by_projection or [()] * len(content_hashes))

    def project(_norma, as_of):
        content_hash = next(values)
        input_hash = next(inputs)
        norma_id = getattr(_norma, "pk", _norma)
        return SimpleNamespace(
            norma_id=norma_id,
            as_of=as_of,
            status=status,
            input_sha256=input_hash,
            content_sha256=content_hash,
            coverage={},
            devices=next(device_sets),
        )

    def persist(projection):
        snapshot = NormativeSnapshot.objects.create(
            norma_id=projection.norma_id,
            as_of=projection.as_of,
            status=projection.status,
            input_sha256=projection.input_sha256,
            content_sha256=projection.content_sha256,
            coverage_json=projection.coverage,
        )
        for item in projection.devices:
            SnapshotDispositivo.objects.create(
                snapshot=snapshot,
                base_device=item.source,
                structural_key=item.source.structural_key,
                text=item.text,
                legal_status=item.legal_status,
                provenance_json=item.provenance,
            )
        return snapshot

    monkeypatch.setattr(collection_evidence, "project_norma_as_of", project)
    monkeypatch.setattr(collection_evidence, "persist_projection", persist)


def _setup_collection():
    owner = User.objects.create_user("evidence-owner", password="secret")
    collection = Collection.objects.create(user=owner, name="Pesquisa tributária")
    norma = Norma.objects.create(
        tipo="Lei Complementar", numero="120", ano=2010, status=Norma.Status.CONSOLIDATED
    )
    collection.normas.add(norma)
    return owner, collection, norma


def _device_projection(norma, key, text, *, provenance=None):
    text_hash = hashlib.sha256(text.encode()).hexdigest()
    document = DocumentoNormativo.objects.create(
        document_key=hashlib.sha256(
            f"doc-{norma.pk}-{key}-{text}-{uuid.uuid4()}".encode()
        ).hexdigest(),
        norma=norma,
        source_kind=DocumentoNormativo.SourceKind.LEGACY,
        source_ref="qa://device-evidence-test",
        content_sha256=text_hash,
    )
    extraction = ExtracaoDocumento.objects.create(
        documento=document,
        extractor_version="test-v1",
        policy_fingerprint="a" * 64,
        text_version="test-v1",
        raw_text=text,
        legal_text=text,
        raw_text_sha256=text_hash,
        legal_text_sha256=text_hash,
        extraction_sha256=hashlib.sha256(f"extract-{document.pk}".encode()).hexdigest(),
    )
    source = DocumentoDispositivo.objects.create(
        extracao=extraction,
        structural_key=key,
        tipo="artigo",
        numero="1º",
        ordem=1,
        texto=text,
    )
    return SimpleNamespace(
        source=source,
        text=text,
        legal_status="in_force",
        provenance=provenance or {"source": "reviewed-test"},
    )


def test_saving_new_evidence_version_preserves_the_previous_snapshot(monkeypatch):
    owner, collection, norma = _setup_collection()
    _save_projection(
        monkeypatch,
        status=NormativeSnapshot.Status.COMPLETE,
        content_hashes=["a" * 64, "b" * 64],
    )

    first = collection_evidence.save_collection_evidence(
        collection=collection, owner_id=owner.pk, norma=norma, as_of=date(2026, 1, 10)
    )
    second = collection_evidence.save_collection_evidence(
        collection=collection, owner_id=owner.pk, norma=norma, as_of=date(2026, 1, 10)
    )

    assert (first.version, second.version) == (1, 2)
    assert first.snapshot_id != second.snapshot_id
    assert first.snapshot.content_sha256 == "a" * 64
    assert second.snapshot.content_sha256 == "b" * 64
    assert first.evidence_hash != second.evidence_hash
    assert CollectionEvidenceVersion.objects.count() == 2


def test_collection_evidence_is_owner_scoped_and_another_user_cannot_read_or_save():
    owner, collection, norma = _setup_collection()
    other = User.objects.create_user("evidence-other", password="secret")
    client = Client()
    client.force_login(other)

    response = client.get(f"/colecoes/{collection.pk}/")
    assert response.status_code == 404

    with pytest.raises(PermissionError):
        collection_evidence.save_collection_evidence(
            collection=collection,
            owner_id=other.pk,
            norma=norma,
            as_of=date(2026, 1, 10),
        )
    assert CollectionEvidenceVersion.objects.count() == 0
    assert NormativeSnapshot.objects.count() == 0


def test_inconclusive_projection_is_saved_with_explicit_nonlegal_status(monkeypatch):
    owner, collection, norma = _setup_collection()
    _save_projection(
        monkeypatch,
        status=NormativeSnapshot.Status.NOT_RECONSTRUCTABLE,
        content_hashes=["c" * 64],
    )

    saved = collection_evidence.save_collection_evidence(
        collection=collection, owner_id=owner.pk, norma=norma, as_of=date(2026, 1, 10)
    )

    assert saved.result == CollectionEvidenceVersion.Result.INCONCLUSIVE
    assert saved.get_result_display() == "Não reconstruível"
    assert saved.snapshot.status == NormativeSnapshot.Status.NOT_RECONSTRUCTABLE


def test_saved_collection_evidence_cannot_be_edited_or_bulk_deleted(monkeypatch):
    owner, collection, norma = _setup_collection()
    _save_projection(
        monkeypatch,
        status=NormativeSnapshot.Status.PARTIAL,
        content_hashes=["d" * 64],
    )
    saved = collection_evidence.save_collection_evidence(
        collection=collection, owner_id=owner.pk, norma=norma, as_of=date(2026, 1, 10)
    )

    saved.result = CollectionEvidenceVersion.Result.COMPLETE
    with pytest.raises(ValidationError, match="imutáveis"):
        saved.save()
    with pytest.raises(ValidationError, match="imutáveis"):
        CollectionEvidenceVersion.objects.filter(pk=saved.pk).update(result="complete")
    with pytest.raises(ValidationError, match="preservadas"):
        CollectionEvidenceVersion.objects.filter(pk=saved.pk).delete()
    with pytest.raises(ValidationError, match="atualizadas em lote"):
        CollectionEvidenceVersion.objects.bulk_update([saved], ["result"])
    assert CollectionEvidenceVersion.objects.get(pk=saved.pk).result == "partial"


def test_changed_projection_is_a_review_notice_not_an_automatic_overwrite(monkeypatch):
    owner, collection, norma = _setup_collection()
    _save_projection(
        monkeypatch,
        status=NormativeSnapshot.Status.COMPLETE,
        content_hashes=["e" * 64, "f" * 64],
    )
    saved = collection_evidence.save_collection_evidence(
        collection=collection, owner_id=owner.pk, norma=norma, as_of=date(2026, 1, 10)
    )

    impacts = collection_evidence.collection_evidence_impact(
        collection, current_date=date(2026, 10, 8)
    )

    assert impacts[0]["comparison"] == "changed"
    assert impacts[0]["saved"].pk == saved.pk
    assert saved.snapshot.content_sha256 == "e" * 64


def test_changed_evidence_provenance_is_flagged_even_when_text_hash_is_identical(monkeypatch):
    owner, collection, norma = _setup_collection()
    _save_projection(
        monkeypatch,
        status=NormativeSnapshot.Status.COMPLETE,
        content_hashes=["e" * 64, "e" * 64],
        input_hashes=["a" * 64, "b" * 64],
    )
    collection_evidence.save_collection_evidence(
        collection=collection, owner_id=owner.pk, norma=norma, as_of=date(2026, 1, 10)
    )

    impacts = collection_evidence.collection_evidence_impact(
        collection, current_date=date(2026, 10, 8)
    )

    assert impacts[0]["comparison"] == "provenance_changed"
    assert impacts[0]["content_changed"] is False
    assert impacts[0]["provenance_changed"] is True


def test_device_versions_have_independent_sequence_and_remain_linked_to_full_snapshot(monkeypatch):
    owner, collection, norma = _setup_collection()
    key = "a" * 64
    first_device = _device_projection(norma, key, "Redação inicial")
    second_device = _device_projection(norma, key, "Redação revisada")
    _save_projection(
        monkeypatch,
        status=NormativeSnapshot.Status.COMPLETE,
        content_hashes=["a" * 64, "b" * 64, "c" * 64],
        devices_by_projection=[(first_device,), (second_device,), (second_device,)],
    )

    first = collection_evidence.save_collection_evidence(
        collection=collection,
        owner_id=owner.pk,
        norma=norma,
        as_of=date(2026, 1, 10),
        device_key=key,
    )
    second = collection_evidence.save_collection_evidence(
        collection=collection,
        owner_id=owner.pk,
        norma=norma,
        as_of=date(2026, 1, 10),
        device_key=key,
    )
    whole_norm = collection_evidence.save_collection_evidence(
        collection=collection,
        owner_id=owner.pk,
        norma=norma,
        as_of=date(2026, 1, 10),
    )

    assert (first.version, second.version, whole_norm.version) == (1, 2, 1)
    assert first.device_key == second.device_key == key
    assert first.snapshot.dispositivos.get(structural_key=key).text == "Redação inicial"
    assert second.snapshot.dispositivos.get(structural_key=key).text == "Redação revisada"
    assert first.evidence_hash != second.evidence_hash


def test_device_impact_ignores_unrelated_device_changes_and_detects_selected_change(monkeypatch):
    owner, collection, norma = _setup_collection()
    selected_key, other_key = "a" * 64, "b" * 64
    initial_selected = _device_projection(norma, selected_key, "Artigo selecionado")
    initial_other = _device_projection(norma, other_key, "Texto antigo")
    current_selected = _device_projection(norma, selected_key, "Artigo selecionado")
    current_other = _device_projection(norma, other_key, "Texto alterado")
    changed_selected = _device_projection(norma, selected_key, "Artigo alterado")
    _save_projection(
        monkeypatch,
        status=NormativeSnapshot.Status.COMPLETE,
        content_hashes=["a" * 64, "b" * 64, "c" * 64],
        input_hashes=["a" * 64, "b" * 64, "c" * 64],
        devices_by_projection=[
            (initial_selected, initial_other),
            (current_selected, current_other),
            (changed_selected, current_other),
        ],
    )
    saved = collection_evidence.save_collection_evidence(
        collection=collection,
        owner_id=owner.pk,
        norma=norma,
        as_of=date(2026, 1, 10),
        device_key=selected_key,
    )

    unrelated_change = collection_evidence.collection_evidence_impact(
        collection, current_date=date(2026, 10, 8)
    )
    selected_change = collection_evidence.collection_evidence_impact(
        collection, current_date=date(2026, 10, 8)
    )

    assert unrelated_change[0]["comparison"] == "unchanged"
    assert unrelated_change[0]["saved"].pk == saved.pk
    assert selected_change[0]["comparison"] == "changed"


def test_device_evidence_rejects_key_missing_from_reviewed_projection(monkeypatch):
    owner, collection, norma = _setup_collection()
    _save_projection(
        monkeypatch,
        status=NormativeSnapshot.Status.COMPLETE,
        content_hashes=["a" * 64],
    )

    with pytest.raises(ValueError, match="não está disponível"):
        collection_evidence.save_collection_evidence(
            collection=collection,
            owner_id=owner.pk,
            norma=norma,
            as_of=date(2026, 1, 10),
            device_key="a" * 64,
        )

    assert CollectionEvidenceVersion.objects.count() == 0
    assert NormativeSnapshot.objects.count() == 0


def test_collection_form_offers_reviewed_structural_device_and_saves_selected_reference(
    monkeypatch,
):
    owner, collection, norma = _setup_collection()
    key = structural_key("root", "artigo", "1º")
    Dispositivo.objects.create(
        norma=norma,
        tipo="artigo",
        numero="1º",
        texto="Texto do artigo",
        ordem=1,
        structural_key=key,
    )
    source = _device_projection(norma, key, "Texto do artigo")
    _save_projection(
        monkeypatch,
        status=NormativeSnapshot.Status.COMPLETE,
        content_hashes=["a" * 64, "b" * 64],
        devices_by_projection=[(source,), (source,)],
    )
    client = Client()
    client.force_login(owner)

    page = client.get(f"/colecoes/{collection.pk}/")
    assert page.status_code == 200
    assert "Referência a preservar" in page.content.decode()
    assert "Art. 1º" in page.content.decode()

    response = client.post(
        f"/colecoes/{collection.pk}/",
        {
            "action": "save_evidence",
            "norma_id": norma.pk,
            "as_of": "2026-01-10",
            "device_key": key,
        },
    )

    assert response.status_code == 302
    saved = CollectionEvidenceVersion.objects.get(collection=collection, norma=norma)
    assert saved.device_key == key
    assert saved.snapshot.dispositivos.get(structural_key=key).text == "Texto do artigo"
    detail = client.get(f"/colecoes/{collection.pk}/")
    assert detail.status_code == 200
    assert "mode=precedent&amp;device_id=" in detail.content.decode()


def test_collection_detail_exposes_explicit_date_and_nonconclusive_language(monkeypatch):
    owner, collection, norma = _setup_collection()
    client = Client()
    client.force_login(owner)
    response = client.get(f"/colecoes/{collection.pk}/")

    assert response.status_code == 200
    body = response.content.decode()
    assert 'name="as_of"' in body
    assert "Salvar versão histórica" in body
    assert "não determina qual redação se aplica" in body
    assert f"/normas/{norma.pk}/" in body


def test_collection_detail_post_saves_an_explicit_version_and_redirects(monkeypatch):
    owner, collection, norma = _setup_collection()
    _save_projection(
        monkeypatch,
        status=NormativeSnapshot.Status.COMPLETE,
        content_hashes=["9" * 64],
    )
    client = Client()
    client.force_login(owner)

    response = client.post(
        f"/colecoes/{collection.pk}/",
        {"action": "save_evidence", "norma_id": norma.pk, "as_of": "2026-01-10"},
    )

    assert response.status_code == 302
    assert response.url == f"/colecoes/{collection.pk}/"
    saved = CollectionEvidenceVersion.objects.get(collection=collection, norma=norma)
    assert saved.owner_id == owner.pk
    assert saved.snapshot.as_of == date(2026, 1, 10)
    assert saved.result == CollectionEvidenceVersion.Result.COMPLETE


def test_save_action_rejects_future_dates_and_norms_not_in_the_collection():
    owner, collection, norma = _setup_collection()
    key = structural_key("root", "artigo", "1º")
    Dispositivo.objects.create(
        norma=norma,
        tipo="artigo",
        numero="1º",
        texto="Texto do artigo",
        ordem=1,
        structural_key=key,
    )
    client = Client()
    client.force_login(owner)

    future = client.post(
        f"/colecoes/{collection.pk}/",
        {
            "action": "save_evidence",
            "norma_id": norma.pk,
            "as_of": "2999-01-01",
            "device_key": key,
        },
    )
    assert future.status_code == 400
    body = future.content.decode()
    assert "não pode estar no futuro" in body
    assert 'value="2999-01-01"' in body
    assert f'<option value="{key}" selected>' in body

    collection.normas.remove(norma)
    absent = client.post(
        f"/colecoes/{collection.pk}/",
        {"action": "save_evidence", "norma_id": norma.pk, "as_of": "2026-01-10"},
    )
    assert absent.status_code == 400
    assert CollectionEvidenceVersion.objects.count() == 0
    assert NormativeSnapshot.objects.count() == 0
