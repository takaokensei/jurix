from __future__ import annotations

import json
from hashlib import sha256
from types import SimpleNamespace

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from src.apps.ingestion.management.commands.build_pilot_manifest import _document_strata
from src.apps.legislation.document_models import DocumentoNormativo
from src.apps.legislation.models import Norma


def _document(*, source_ref, synthetic, index, act_type="Lei", year=2018,
              include_synthetic_marker=True):
    digest = sha256(source_ref.encode()).hexdigest()
    return DocumentoNormativo.objects.create(
        document_key=digest,
        source_kind=DocumentoNormativo.SourceKind.ARCHIVE,
        source_ref=source_ref,
        archive_sha256=sha256(b"archive").hexdigest(),
        entry_index=index,
        entry_name=f"municipal/{act_type}_{year}_{index}.pdf",
        original_filename=f"{act_type}_{year}_{index}.pdf",
        role=DocumentoNormativo.Role.UNDETERMINED,
        content_sha256=digest,
        metadata_json={
            **({"synthetic": synthetic} if include_synthetic_marker else {}),
            "identity_candidate": {"type": act_type, "year": year},
        },
    )


@pytest.mark.django_db
def test_v1_manifest_keeps_legacy_schema_and_refuses_overwrite(tmp_path):
    Norma.objects.create(
        tipo="Lei", numero="123", ano=2020, sapl_id=12345,
        sapl_url="https://sapl.example/norma/12345", ementa="Ementa pública",
        identity_key="BR-RN-NATAL|lei|municipal_lo|123|2020",
    )
    output = tmp_path / "pilot-v1.jsonl"
    call_command("build_pilot_manifest", output=str(output), schema_version="1")
    row = json.loads(output.read_text(encoding="utf-8").splitlines()[0])
    assert set(row) == {
        "norma_id", "sapl_id", "identifier", "ementa", "source_url",
        "ai_review_status", "human_review_status", "annotation_status", "notes",
    }
    assert row["human_review_status"] == "pending"
    with pytest.raises(CommandError, match="recusando sobrescrever"):
        call_command("build_pilot_manifest", output=str(output), schema_version="1")


@pytest.mark.django_db
def test_v2_manifest_is_provenance_first_and_excludes_synthetic_gold(tmp_path):
    norma = Norma.objects.create(
        tipo="Lei Complementar", numero="77", ano=2019, sapl_id=777,
        sapl_url="https://sapl.example/norma/777", ementa="Candidata pendente",
        identity_key="BR-RN-NATAL|lei_complementar|municipal_lc|77|2019",
    )
    _document(source_ref="archive:human-candidate", synthetic=False, index=7,
              act_type="Lei Complementar", year=2019)
    _document(source_ref="archive:synthetic-fixture", synthetic=True, index=8)
    synthetic_norma = Norma.objects.create(
        tipo="Lei", numero="9999", ano=2090, sapl_id=999999,
        ementa="Fixture sintética que não pode virar candidata humana.",
        identity_key="BR-RN-NATAL|lei|municipal_lo|9999|2090",
        identity_json={"synthetic_fixture": True},
    )
    unkeyed_norma = Norma.objects.create(
        tipo="Lei", numero="78", ano=2019, sapl_id=778,
        ementa="Registro legado sem identity_key estável.",
    )
    output = tmp_path / "pilot-v2.jsonl"
    call_command(
        "build_pilot_manifest", output=str(output), schema_version="2",
        document_sample_size=40,
    )
    rows = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
    header, *records = rows
    assert header["schema_version"] == 2
    assert header["selected_document_count"] == 1
    assert header["selected_norma_candidate_count"] == 1
    assert header["synthetic_fixtures_are_gold"] is False
    norm_rows = [row for row in records if row["record_type"] == "norma_review_candidate"]
    document_rows = [row for row in records if row["record_type"] == "document_review_candidate"]
    assert len(norm_rows) == 1 and norm_rows[0]["norma_id"] == norma.pk
    assert norm_rows[0]["human_review_status"] == "pending"
    assert norm_rows[0]["gold_eligible"] is False
    assert synthetic_norma.pk not in {row["norma_id"] for row in norm_rows}
    assert unkeyed_norma.pk not in {row["norma_id"] for row in norm_rows}
    assert all(isinstance(row["norma_key"], str) and row["norma_key"] for row in norm_rows)
    assert len(document_rows) == 1
    assert document_rows[0]["document_key"] == "archive:human-candidate" or (
        document_rows[0]["document_sha256"] == sha256(b"archive:human-candidate").hexdigest()
    )
    assert document_rows[0]["entry_index"] == 7
    assert document_rows[0]["synthetic_fixture"] is False
    assert document_rows[0]["gold_eligible"] is False
    assert document_rows[0]["strata"]["period"] == "2010-2019"


@pytest.mark.django_db
def test_v1_manifest_excludes_synthetic_norma_even_when_it_has_sapl_id(tmp_path):
    Norma.objects.create(
        tipo="Lei", numero="9998", ano=2090, sapl_id=999998,
        ementa="Fixture que não pode entrar no piloto.",
        identity_key="BR-RN-NATAL|lei|municipal_lo|9998|2090",
        identity_json={"synthetic_fixture": True},
    )
    output = tmp_path / "pilot-v1-synthetic.jsonl"
    call_command("build_pilot_manifest", output=str(output), schema_version="1")
    assert output.read_text(encoding="utf-8") == ""


@pytest.mark.django_db
def test_v2_document_sample_is_deterministic_and_bounded(tmp_path):
    for index in range(5):
        _document(source_ref=f"archive:candidate:{index}", synthetic=False, index=index,
                  act_type="Decreto" if index % 2 else "Lei", year=2001 + index * 5)
    first = tmp_path / "pilot-v2-first.jsonl"
    second = tmp_path / "pilot-v2-second.jsonl"
    for output in (first, second):
        call_command(
            "build_pilot_manifest", output=str(output), schema_version="2",
            document_sample_size=3,
        )
    parsed = [json.loads(line) for line in first.read_text(encoding="utf-8").splitlines()]
    repeated = [json.loads(line) for line in second.read_text(encoding="utf-8").splitlines()]
    assert parsed == repeated
    documents = [row for row in parsed if row["record_type"] == "document_review_candidate"]
    assert len(documents) == 3
    assert len({row["document_key"] for row in documents}) == 3
    assert all(row["human_review_required"] and row["gold_eligible"] is False for row in documents)


@pytest.mark.django_db
def test_v2_includes_legacy_archive_candidate_when_synthetic_marker_is_absent(tmp_path):
    _document(source_ref="archive:legacy-no-marker", synthetic=False, index=3,
              include_synthetic_marker=False)
    output = tmp_path / "pilot-v2-legacy.jsonl"
    call_command(
        "build_pilot_manifest", output=str(output), schema_version="2",
        document_sample_size=40,
    )
    rows = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
    candidate = next(row for row in rows if row["record_type"] == "document_review_candidate")
    assert candidate["document_sha256"] == sha256(b"archive:legacy-no-marker").hexdigest()
    assert candidate["synthetic_fixture"] is False


@pytest.mark.parametrize(
    ("page_methods", "expected"),
    [
        ({"native": 4, "ocr": 0, "unreadable": 0}, "native"),
        ({"native": 0, "ocr": 4, "unreadable": 0}, "ocr"),
        ({"native": 3, "ocr": 1, "unreadable": 0}, "mixed"),
        ({"native": 0, "ocr": 0, "unreadable": 2}, "unreadable"),
        ({"native": 0, "ocr": 0, "unreadable": 0}, "unknown"),
    ],
)
def test_document_strata_derives_extraction_mode_from_page_method_counts(
    page_methods, expected
):
    document = SimpleNamespace(
        metadata_json={"identity_candidate": {"type": "decreto", "year": 2005}},
        accepted_extraction=SimpleNamespace(quality_json={"page_methods": page_methods}),
        source_kind="archive",
        role="original",
    )

    assert _document_strata(document)["extraction_mode"] == expected


def test_document_strata_marks_unaccepted_extraction_as_candidate():
    document = SimpleNamespace(
        metadata_json={"identity_candidate": {"type": "decreto", "year": 2005}},
        accepted_extraction=None,
        pilot_extractions=[
            SimpleNamespace(quality_json={"page_methods": {"native": 2, "ocr": 1}})
        ],
        source_kind="archive",
        role="original",
    )

    assert _document_strata(document)["extraction_mode"] == "candidate_mixed"
