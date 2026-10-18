import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from src.processing.evidence_export import (
    build_evidence_package,
    render_evidence_json,
    render_evidence_markdown,
)


def _source(**overrides):
    source = {
        "citation_id": "jurix:norma:31:dispositivo:81",
        "citation_index": 1,
        "citation_label": "Lei nº 8.205/2026, Art. 1º",
        "norma_ref": "Lei nº 8.205/2026",
        "norma_id": 31,
        "dispositivo_ref": "Art. 1º",
        "source_type": "Fonte normativa primária",
        "contribution": "Trecho que institui a política",
        "source_kind": "sapl_legislative_matter",
        "status_label": "Em tramitação no SAPL",
        "matter_status": True,
        "matter_result": None,
        "consulted_at": "2026-10-09T18:00:00-03:00",
        "evidence_scope": "reviewed_norma",
        "evidence_text": "Texto oficial do dispositivo.",
        "data_publicacao": "2026-04-02",
        "data_vigencia": "2026-04-02",
        "temporal_status": "vigente",
        "source_url": "https://sapl.natal.rn.leg.br/norma/9386",
        "document_sha256": "a" * 64,
        "page": 2,
        "span": {"start": 10, "end": 50},
        "span_basis": "page-artifact-stripped-extraction",
        "private_api_key": "must-not-export",
    }
    source.update(overrides)
    return source


def test_export_dto_whitelists_provenance_and_markdown_links_to_official_source():
    package = build_evidence_package(
        [_source()],
        corpus_revision={
            "revision": "corpus-r7",
            "digest": "C" * 64,
            "completeness": "partial",
            "source": "municipal-natal",
            "updated_at": "2026-10-07T12:00:00Z",
            "secret": "must-not-export",
        },
        generated_at=datetime(2026, 10, 8, tzinfo=UTC),
    )

    row = package["sources"][0]
    markdown = render_evidence_markdown(package)
    serialized = render_evidence_json(package)
    assert row["citation_id"] == "jurix:norma:31:dispositivo:81"
    assert row["document_sha256"] == "a" * 64
    assert row["page"] == 2
    assert row["source_kind"] == "sapl_legislative_matter"
    assert row["status_label"] == "Em tramitação no SAPL"
    assert row["matter_status"] is True
    assert row["consulted_at"] == "2026-10-09T18:00:00-03:00"
    assert row["span"] == {"start": 10, "end": 50}
    assert row["span_basis"] == "page-artifact-stripped-extraction"
    assert "[Lei nº 8.205/2026, Art. 1º](<https://sapl.natal.rn.leg.br/norma/9386>)" in markdown
    assert "Texto oficial do dispositivo." in markdown
    assert "must-not-export" not in serialized
    assert package["corpus_revision"] == {
        "revision": "corpus-r7",
        "digest": "c" * 64,
        "completeness": "partial",
        "updated_at": "2026-10-07",
        "source": "municipal-natal",
    }


def test_export_removes_unsafe_urls_and_rejects_unreviewed_raw_payload_fields():
    package = build_evidence_package(
        [
            _source(
                source_url="javascript:alert(1)",
                pdf_url="file:///secret.pdf",
                local_pdf_url="/normas/documentos/not-a-uuid/pdf/",
                user_prompt="confidential case text",
                graph_relation={"private": "metadata"},
                span={"start": 0, "end": 20, "raw_text": "private"},
            )
        ]
    )

    row = package["sources"][0]
    serialized = render_evidence_json(package)
    assert row["official_url"] is None
    assert row["local_pdf_url"] is None
    assert row["span"] == {"start": 0, "end": 20}
    assert "confidential case text" not in serialized
    assert "private" not in serialized


def test_historical_export_includes_version_hash_and_uses_unmarked_url():
    package = build_evidence_package(
        [
            _source(
                source_url="https://sapl.natal.rn.leg.br/media/lei.pdf#:~:text=highlight",
                temporal_version={
                    "as_of": "2026-05-01",
                    "legal_status": "in_force",
                    "version_hash": "b" * 64,
                    "source_document_id": "12345678-1234-5678-1234-567812345678",
                    "secret": "must-not-export",
                },
            )
        ]
    )

    row = package["sources"][0]
    assert row["official_url"] == "https://sapl.natal.rn.leg.br/media/lei.pdf"
    assert row["temporal_version"]["version_hash"] == "b" * 64
    assert "secret" not in render_evidence_json(package)


def test_export_rejects_impossible_publication_effective_and_snapshot_dates():
    package = build_evidence_package(
        [
            _source(
                data_publicacao="2026-02-30",
                data_vigencia="2026-13-01",
                temporal_version={
                    "as_of": "2026-02-30",
                    "effective_on": "2026-02-30",
                    "version_hash": "e" * 64,
                },
            )
        ]
    )

    row = package["sources"][0]
    assert row["publication_date"] is None
    assert row["effective_date"] is None
    assert row["temporal_version"] is None


def test_export_dto_matches_shared_browser_contract_fixture():
    fixture_path = Path(__file__).parent / "fixtures" / "evidence_export_parity.json"
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    generated_at = datetime.fromisoformat(fixture["generated_at"].replace("Z", "+00:00"))

    package = build_evidence_package(
        [fixture["source"]],
        corpus_revision=fixture["corpus_revision"],
        corpus_coverage=fixture["corpus_coverage"],
        generated_at=generated_at,
    )
    expected = fixture["expected"]
    assert package["schema_version"] == expected["schema_version"]
    assert package["generated_at"].replace("+00:00", "Z") == expected["generated_at"]
    assert package["corpus_revision"] == expected["corpus_revision"]
    assert package["corpus_coverage"] == expected["corpus_coverage"]
    assert len(package["sources"]) == 1
    source = package["sources"][0]
    assert {key: source.get(key) for key in expected["source_fields"]} == expected["source_fields"]
    assert "raw_text" not in source["span"]


def test_export_orders_sources_by_citation_index_then_stable_id():
    package = build_evidence_package(
        [
            _source(citation_id="z-unindexed", citation_index=None),
            _source(citation_id="c-indexed", citation_index=2),
            _source(citation_id="z-tied", citation_index=1),
            _source(citation_id="a-tied", citation_index=1),
            _source(citation_id="a-unindexed", citation_index=None),
            _source(citation_id="b-invalid-index", citation_index=-1),
        ]
    )

    assert [source["citation_id"] for source in package["sources"]] == [
        "a-tied",
        "z-tied",
        "c-indexed",
        "a-unindexed",
        "b-invalid-index",
        "z-unindexed",
    ]


def test_export_preserves_reviewed_event_snapshot_and_explicit_verification_limit():
    package = build_evidence_package(
        [
            _source(
                temporal_version={
                    "as_of": "2026-05-01",
                    "legal_status": "in_force",
                    "version_hash": "b" * 64,
                    "input_hash": "c" * 64,
                    "snapshot_id": 42,
                    "policy": "normative-projection-v1",
                    "status_note": "Texto projetado para a data consultada.",
                    "secret": "must-not-export",
                },
                coverage={
                    "as_of": "2026-05-01",
                    "status": "complete",
                    "complete": True,
                    "snapshot_id": 42,
                    "version_hash": "b" * 64,
                    "input_hash": "c" * 64,
                    "policy": "normative-projection-v1",
                    "projected_devices": 12,
                    "selected_devices": 12,
                    "internal_path": "C:/private",
                },
                graph_relation={
                    "casefile_id": "d" * 64,
                    "event_id": "event-17",
                    "action": "REVOGA",
                    "review_status": "approved",
                    "effective_status": "effective",
                    "effective_on": "2025-01-01",
                    "publication_on": "2024-12-20",
                    "quote": "Revoga o dispositivo anterior.",
                    "api_key": "must-not-export",
                },
            )
        ]
    )

    row = package["sources"][0]
    markdown = render_evidence_markdown(package)
    serialized = render_evidence_json(package)
    assert row["temporal_version"]["snapshot_id"] == 42
    assert row["temporal_version"]["input_hash"] == "c" * 64
    assert row["graph_relation"]["event_id"] == "event-17"
    assert row["graph_relation"]["casefile_id"] == "d" * 64
    assert row["graph_relation"]["action"] == "REVOGA"
    assert row["projection_coverage"]["selected_devices"] == 12
    assert "Snapshot: `42`" in markdown
    assert "Relação: REVOGA" in markdown
    assert "Limite da verificação" in markdown
    assert "must-not-export" not in serialized
    assert "C:/private" not in serialized


def test_export_states_limits_for_archive_and_partial_temporal_evidence():
    archive = build_evidence_package(
        [_source(evidence_scope="isolated_qa_archive")]
    )["sources"][0]
    partial_temporal = build_evidence_package(
        [
            _source(
                temporal_version={"as_of": "2026-05-01", "version_hash": "b" * 64},
                coverage={"complete": False},
            )
        ]
    )["sources"][0]

    assert "revisão jurídica" in archive["verification_limit"]
    assert "parcial ou incompleta" in partial_temporal["verification_limit"]


def test_markdown_without_sources_is_explicit():
    package = build_evidence_package([])
    assert "Nenhuma fonte estruturada" in render_evidence_markdown(package)


def test_markdown_omits_missing_excerpts_without_reusing_previous_source_text():
    package = build_evidence_package(
        [
            _source(citation_index=1, citation_label="Fonte com excerto", evidence_text="Trecho da primeira fonte."),
            _source(
                citation_id="jurix:norma:32:dispositivo:82",
                citation_index=2,
                citation_label="Fonte sem excerto",
                evidence_text="",
            ),
        ]
    )

    markdown = render_evidence_markdown(package)

    assert markdown.count("Evidência:") == 1
    assert "Trecho da primeira fonte." in markdown
    assert "Fonte sem excerto" in markdown
    assert "Evidência: “Trecho da primeira fonte.”" not in markdown.split("Fonte sem excerto", 1)[1]


def test_markdown_source_without_excerpt_does_not_raise():
    package = build_evidence_package([_source(evidence_text=None)])

    markdown = render_evidence_markdown(package)

    assert "Lei nº 8.205/2026, Art. 1º" in markdown
    assert "Evidência:" not in markdown


def test_corpus_revision_drops_invalid_digest_completeness_and_date():
    package = build_evidence_package(
        [],
        corpus_revision={
            "revision": "  r8  ",
            "digest": "not-a-sha256",
            "completeness": "pretend-complete",
            "updated_at": "2026-99-99",
        },
    )

    assert package["corpus_revision"] == {"revision": "r8"}


def test_corpus_coverage_matches_safe_versioned_contract():
    package = build_evidence_package(
        [_source()],
        corpus_coverage={
            "coverage_status": "partial",
            "corpus_revision": {"revision": 7, "digest": "c" * 64},
            "scope_limited": True,
            "checked_until": "2024-12-31",
            "sources_checked": [
                {
                    "source": "sapl",
                    "jurisdiction": "BR-RN-NATAL",
                    "series": "municipal_lc",
                    "period_start": "2010-01-01",
                    "period_end": "2024-12-31",
                    "checked_until": "2024-12-31",
                    "source_checksum": "d" * 64,
                    "coverage_status": "partial",
                    "missing_intervals": [
                        {"start": "2015-01-01", "end": "2015-12-31", "internal_path": "C:/private"}
                    ],
                    "pending_review": 4,
                    "last_success_at": "2026-10-12T18:30:00-03:00",
                    "internal_path": "C:/private/archive",
                }
            ],
            "missing_intervals": [
                {
                    "source": "sapl",
                    "jurisdiction": "BR-RN-NATAL",
                    "series": "municipal_lc",
                    "start": "2015-01-01",
                    "end": "2015-12-31",
                    "internal_path": "C:/private",
                }
            ],
            "pending_review": 4,
            "reason": "registered_scopes_only_not_a_universal_completeness_claim",
            "private_token": "must-not-export",
        },
    )

    assert package["corpus_coverage"] == {
        "coverage_status": "partial",
        "corpus_revision": {"revision": 7, "digest": "c" * 64},
        "scope_limited": True,
        "checked_until": "2024-12-31",
        "sources_checked": [
            {
                "source": "sapl",
                "jurisdiction": "BR-RN-NATAL",
                "series": "municipal_lc",
                "period_start": "2010-01-01",
                "period_end": "2024-12-31",
                "checked_until": "2024-12-31",
                "source_checksum": "d" * 64,
                "coverage_status": "partial",
                "missing_intervals": [{"start": "2015-01-01", "end": "2015-12-31"}],
                "pending_review": 4,
                "last_success_at": "2026-10-12T18:30:00-03:00",
            }
        ],
        "missing_intervals": [
            {
                "source": "sapl",
                "jurisdiction": "BR-RN-NATAL",
                "series": "municipal_lc",
                "start": "2015-01-01",
                "end": "2015-12-31",
            }
        ],
        "pending_review": 4,
        "reason": "registered_scopes_only_not_a_universal_completeness_claim",
    }
    exported_json = render_evidence_json(package)
    exported_markdown = render_evidence_markdown(package)
    assert "must-not-export" not in exported_json
    assert "C:/private" not in exported_json
    assert "must-not-export" not in exported_markdown
    assert "C:/private" not in exported_markdown
    assert "Cobertura do acervo: **parcial**." in exported_markdown
    assert "Corte verificado: **2024-12-31**." in exported_markdown
    assert "Documentos pendentes de revisão: **4**." in exported_markdown
    assert "não comprova completude universal" in exported_markdown
    assert "Intervalo sem cobertura registrada" in exported_markdown


def test_corpus_coverage_uses_unknown_for_invalid_and_missing_values():
    package = build_evidence_package(
        [],
        corpus_coverage={
            "coverage_status": "complete",
            "corpus_revision": {"revision": True, "digest": "bad"},
            "checked_until": "2026-10-12T00:00:00Z",
            "sources_checked": [
                {
                    "coverage_status": "verified-everything",
                    "period_start": "2024-99-01",
                    "missing_intervals": [{"start": "nonsense", "end": None}],
                    "pending_review": True,
                    "last_success_at": "2026-10-12T10:00:00",
                }
            ],
            "pending_review": -1,
            "reason": "arbitrary-private-reason",
        },
    )

    assert package["corpus_coverage"] == {
        "coverage_status": "unknown",
        "corpus_revision": {"revision": None, "digest": None},
        "scope_limited": False,
        "checked_until": None,
        "sources_checked": [
            {
                "source": None,
                "jurisdiction": None,
                "series": None,
                "period_start": None,
                "period_end": None,
                "checked_until": None,
                "source_checksum": None,
                "coverage_status": "unknown",
                "missing_intervals": [],
                "pending_review": None,
                "last_success_at": None,
            }
        ],
        "missing_intervals": None,
        "pending_review": None,
        "reason": None,
    }


def test_corpus_coverage_malformed_container_values_fail_closed_without_raising():
    package = build_evidence_package(
        [],
        corpus_coverage={
            "coverage_status": [],
            "corpus_revision": {"revision": {"unexpected": True}, "digest": []},
            "sources_checked": [
                {
                    "coverage_status": {},
                    "pending_review": {"unexpected": True},
                    "source_checksum": [],
                }
            ],
            "missing_intervals": [{"start": [], "end": {"unexpected": True}}],
            "pending_review": [],
            "reason": [],
        },
    )

    assert package["corpus_coverage"]["coverage_status"] == "unknown"
    assert package["corpus_coverage"]["corpus_revision"] == {"revision": None, "digest": None}
    assert package["corpus_coverage"]["sources_checked"][0]["coverage_status"] == "unknown"
    assert package["corpus_coverage"]["pending_review"] is None
    assert package["corpus_coverage"]["reason"] is None
    markdown = render_evidence_markdown(package)
    assert "Cobertura do acervo: **não verificada**." in markdown
    assert "arbitrary-private-reason" not in markdown


def test_corpus_coverage_export_rejects_private_scope_ids_and_incomplete_reviewed_claims():
    package = build_evidence_package(
        [],
        corpus_coverage={
            "coverage_status": "reviewed",
            "corpus_revision": {"revision": 3, "digest": "a" * 64},
            "scope_limited": True,
            "checked_until": "2024-12-31",
            "sources_checked": [{
                "source": "C:/private/archive",
                "jurisdiction": "BR-RN-NATAL",
                "series": "municipal_lc",
                "period_start": "2000-01-01",
                "period_end": "2024-12-31",
                "checked_until": "2024-12-31",
                "source_checksum": "C:/private/archive",
                "coverage_status": "reviewed",
                "missing_intervals": [],
                "pending_review": 0,
            }],
            "missing_intervals": [],
            "pending_review": 0,
            "reason": "registered_scopes_only_not_a_universal_completeness_claim",
        },
    )

    coverage = package["corpus_coverage"]
    assert coverage["coverage_status"] == "partial"
    assert coverage["sources_checked"][0]["coverage_status"] == "partial"
    assert coverage["sources_checked"][0]["source"] is None
    assert coverage["sources_checked"][0]["source_checksum"] is None
    assert "C:/private/archive" not in render_evidence_json(package)


@pytest.mark.parametrize("period_end", ["2024-99-99", "1999-12-31"])
def test_corpus_coverage_export_downgrades_invalid_or_reversed_period_bounds(period_end):
    package = build_evidence_package(
        [],
        corpus_coverage={
            "coverage_status": "reviewed",
            "corpus_revision": {"revision": 3, "digest": "a" * 64},
            "scope_limited": True,
            "checked_until": "2024-12-31",
            "sources_checked": [{
                "source": "sapl",
                "jurisdiction": "BR-RN-NATAL",
                "series": "municipal_lc",
                "period_start": "2000-01-01",
                "period_end": period_end,
                "checked_until": "2024-12-31",
                "source_checksum": "b" * 64,
                "coverage_status": "reviewed",
                "missing_intervals": [],
                "pending_review": 0,
            }],
            "missing_intervals": [],
            "pending_review": 0,
        },
    )

    coverage = package["corpus_coverage"]
    assert coverage["coverage_status"] == "partial"
    assert coverage["sources_checked"][0]["coverage_status"] == "partial"
