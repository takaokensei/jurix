from src.processing.normative_consolidation_preview import (
    build_article_23_snapshot,
    build_article_150_snapshot,
    build_lc271_consolidation_previews,
)


def test_lc271_preview_accepts_complete_article_20_replacement():
    previews = build_lc271_consolidation_previews([
        {
            "article_number": "20",
            "before": {"quote": "Art. 20. Redação anterior."},
            "after": {"quote": "Art. 20. Redação integral nova."},
        },
    ])

    assert len(previews) == 1
    assert previews[0]["status"] == "candidate_integrated"
    assert previews[0]["text"] == "Art. 20. Redação integral nova."


def test_lc271_preview_rejects_internal_omission_even_when_metadata_says_complete():
    previews = build_lc271_consolidation_previews([
        {
            "article_number": "20",
            "before": {"quote": "Art. 20. Redação anterior completa."},
            "after": {
                "quote": "Art. 20. Primeiro trecho ... último trecho.",
                "omitted_following_text": False,
            },
        },
    ])

    assert previews == []


def test_article_23_preview_preserves_five_paragraphs_and_appends_sixth():
    baseline = (
        "Art. 23. Base. § 1º Um. § 2º Dois. § 3º Três. "
        "§ 4º Quatro. § 5º Cinco."
    )
    amendment = "Art. 23. ................................ § 6º Texto novo."

    result = build_article_23_snapshot(baseline, amendment)

    assert result["status"] == "candidate_integrated"
    assert result["added_units"] == ["§ 6º"]
    assert result["text"] == f"{baseline}\n§ 6º Texto novo."


def test_article_150_preview_replaces_only_the_unique_sole_paragraph():
    baseline = "Art. 150. Caput preservado. Parágrafo único. Data antiga."
    amendment = "Art. 150. .... Parágrafo único. Data nova."

    result = build_article_150_snapshot(baseline, amendment)

    assert result["status"] == "candidate_integrated"
    assert result["preserved_units"] == ["caput"]
    assert result["replaced_units"] == ["Parágrafo único"]
    assert result["text"] == "Art. 150. Caput preservado.\nParágrafo único. Data nova."
