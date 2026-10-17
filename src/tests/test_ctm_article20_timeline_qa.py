from types import SimpleNamespace

from src.apps.ingestion.management.commands.inspect_ctm_article20_timeline_qa import (
    _candidate_row,
)


def _candidate(*, article="20", synthetic=False):
    identity = {
        "jurisdiction": "BR-RN-NATAL",
        "type": "Lei Complementar",
        "number": "271",
        "year": 2025,
    }
    if synthetic:
        identity["synthetic_fixture"] = True
    document = SimpleNamespace(
        public_id="d4bd3f69-cf53-47a6-9c64-b670bb7ad998",
        source_kind="sapl",
        metadata_json={
            "identity_candidate": identity,
            "edition_candidate": {"declared_value_year": 2025},
        },
        review_status="pending",
    )
    extraction = SimpleNamespace(documento=document, status="complete")
    return SimpleNamespace(
        extracao=extraction,
        target_reference_json={
            "type_candidate": "Lei",
            "number_candidate": "3.882",
            "year_candidate": 1989,
            "structural_article_number": article,
        },
        evidence_json={
            "action_quote": "passa a vigorar",
            "target_quote": "Art. 20 da Lei nº 3.882/1989",
            "action_page": 1,
            "target_page": 1,
        },
        source_device_label="Art. 1º",
        action="ALTERA",
        revisoes=SimpleNamespace(count=lambda: 0),
    )


def test_timeline_includes_only_exact_public_target_article_candidate():
    row = _candidate_row(_candidate())

    assert row is not None
    assert row["source_identity"] == {
        "type": "Lei Complementar",
        "number": "271",
        "year": 2025,
    }
    assert row["action_candidate"] == "ALTERA"
    assert row["relation_review_count"] == 0


def test_timeline_excludes_other_articles_and_synthetic_sources():
    assert _candidate_row(_candidate(article="21")) is None
    assert _candidate_row(_candidate(synthetic=True)) is None
