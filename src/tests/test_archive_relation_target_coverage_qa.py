from types import SimpleNamespace

from src.apps.ingestion.management.commands.inspect_archive_relation_target_coverage_qa import (
    relation_target_coverage,
)


def _candidate(action, target_type, number, year, source_document_id, *, synthetic=False):
    return SimpleNamespace(
        action=action,
        target_reference_json={
            "type_candidate": target_type,
            "number_candidate": number,
            "year_candidate": year,
        },
        extracao=SimpleNamespace(
            documento_id=source_document_id,
            documento=_document("archive", "Lei", source_document_id, 2003, synthetic=synthetic),
        ),
    )


def _document(kind, norm_type, number, year, *, jurisdiction="BR-RN-NATAL", synthetic=False):
    identity = {
        "type": norm_type,
        "number": number,
        "year": year,
        "jurisdiction": jurisdiction,
    }
    metadata = {"identity_candidate": identity}
    if synthetic:
        metadata["synthetic_fixture"] = True
    return SimpleNamespace(source_kind=kind, metadata_json=metadata)


def _consolidated_edition(number, declared_value_year):
    document = _document("archive", "Lei", number, 1989)
    document.metadata_json["edition_candidate"] = {
        "kind": "official_consolidated_text",
        "declared_value_year": declared_value_year,
    }
    return document


def _norma(norm_type, number, year, *, jurisdiction="BR-RN-NATAL", synthetic=False):
    identity = {"type": norm_type, "jurisdiction": jurisdiction}
    if synthetic:
        identity["synthetic_fixture"] = True
    return SimpleNamespace(tipo=norm_type, numero=number, ano=year, identity_json=identity)


def test_relation_target_coverage_separates_exact_conflict_missing_and_ambiguous():
    candidates = [
        _candidate("ALTERA", "Lei Complementar", "055", 2004, 1),
        _candidate("REVOGA", "Lei", "88", 2000, 2),
        _candidate("ALTERA", "Decreto", "99", 2001, 3),
        _candidate("REVOGA", "Lei", "100", 2002, 4),
        _candidate("REVOGA", "Lei", "101", 2002, 5, synthetic=True),
    ]
    documents = [
        _document("archive", "Lei Complementar", "55", 2004),
        _document("sapl", "Lei Ordinária", "88", 2000),
        _document("archive", "Lei Complementar", "99", 2001),
        _document("archive", "Lei", "100", 2002),
        _document("sapl", "Lei Ordinária", "100", 2002),
        _document("archive", "Lei", "101", 2002, synthetic=True),
        _document("archive", "Lei", "102", 2002, jurisdiction="BR-RN-MOSSORO"),
    ]
    normas = [
        _norma("Lei Complementar", "55", 2004),
        _norma("Lei Ordinária", "88", 2000),
        _norma("Lei Complementar", "99", 2001),
        _norma("Lei", "100", 2002),
        _norma("Lei Ordinária", "100", 2002),
        _norma("Lei", "101", 2002, synthetic=True),
        _norma("Lei", "102", 2002, jurisdiction="BR-RN-MOSSORO"),
    ]

    report = relation_target_coverage(candidates, documents, normas)

    assert report["candidate_count"] == 4
    assert report["source_document_count"] == 4
    assert report["target_identity_categories"] == {
        "multiple_exact_document_identities": 1,
        "one_exact_document_identity": 2,
        "species_conflict_only": 1,
    }
    assert report["target_norma_registry_categories"] == {
        "multiple_exact_norma_identities": 1,
        "one_exact_norma_identity": 2,
        "species_conflict_only": 1,
    }
    assert report["most_repeated_registry_gaps"] == [
        {
            "type": "decreto",
            "number": "99",
            "year": 2001,
            "document_match_status": "species_conflict_only",
            "registry_match_status": "species_conflict_only",
            "candidate_count": 1,
        }
    ]
    assert "No records were changed" in report["interpretation"]


def test_different_official_consolidated_editions_are_temporal_evidence_not_identity_ambiguity():
    candidate = _candidate("ALTERA", "Lei", "3882", 1989, 1)

    report = relation_target_coverage(
        [candidate],
        [
            _consolidated_edition("3882", 2022),
            _consolidated_edition("3882", 2024),
        ],
    )

    assert report["target_identity_categories"] == {
        "multiple_official_consolidated_editions": 1,
    }
    assert report["target_norma_registry_categories"] == {
        "target_norma_identity_absent": 1,
    }
    assert report["most_repeated_registry_gaps"] == [
        {
            "type": "lei",
            "number": "3882",
            "year": 1989,
            "document_match_status": "multiple_official_consolidated_editions",
            "registry_match_status": "target_norma_identity_absent",
            "candidate_count": 1,
        }
    ]
