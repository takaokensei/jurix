import hashlib
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from django.contrib.auth.models import Permission, User
from django.core.exceptions import ValidationError

from src.apps.ingestion.document_relation_candidates import (
    _normalize_pdf_structural_number,
    _single_device_amendment_candidates,
    _target_reference_json,
    extract_document_relation_candidates,
    persist_document_relation_candidates,
)
from src.apps.legislation.document_models import (
    DocumentoNormativo,
    EventoNormativoCandidato,
    ExtracaoDocumento,
    RevisaoEventoNormativoCandidato,
)
from src.apps.legislation.document_relation_review import (
    candidate_target_documents,
    candidate_target_normas,
    candidate_target_type_conflicts,
    review_document_relation_candidate,
)
from src.apps.legislation.models import EventoAlteracao, Norma
from src.processing.document_relation_preview import build_document_relation_preview
from src.processing.ner_extractor import LegalNERExtractor


def test_pdf_replacement_glyphs_normalize_only_unambiguous_device_ordinals():
    section = chr(0xFFFD)
    assert _normalize_pdf_structural_number(
        "paragrafo", "11", f"{section} 11 do art. 66"
    ) == ("11", None)
    assert _normalize_pdf_structural_number(
        "paragrafo", f"1{section}", f"{section}1{section} do art. 68"
    ) == ("1º", "normalized_from_verified_pdf_glyph")
    assert _normalize_pdf_structural_number(
        "paragrafo", f"1{section}", "§ 1º do art. 68"
    ) == ("1º", "normalized_from_verified_pdf_glyph")
    assert _normalize_pdf_structural_number(
        "artigo", f"7{section}", "arts. 7º e 25 da LC 141/2014"
    ) == ("7º", "normalized_from_verified_pdf_glyph")
    assert _normalize_pdf_structural_number(
        "artigo", f"3{section}", "Art. 3º Os arts. 7º e 25 da LC 141/2014"
    ) == ("3º", "normalized_from_verified_pdf_glyph")
    assert _normalize_pdf_structural_number(
        "paragrafo", "2°", "§ 2° do Art. 18"
    ) == ("2º", "normalized_from_verified_pdf_glyph")
    assert _normalize_pdf_structural_number("artigo", "25", "Art. 25") == ("25", None)


@pytest.mark.parametrize(
    ("quote", "paragraph", "article"),
    [
        ("§ 11 do art. 66 da Lei nº 3.882/89", "11", "66"),
        ("§1º do art. 68 da Lei nº 3.882/89", "1º", "68"),
    ],
)
def test_paragraph_relation_keeps_parent_article_and_explicit_short_year(
    quote, paragraph, article
):
    target = _target_reference_json(
        {
            "target_quote": quote,
            "norma_candidate": {"tipo": "Lei", "numero": "3.882", "ano": ""},
            "device_type": "paragrafo",
            "device_number": paragraph,
        }
    )

    assert target["structural_type"] == "paragrafo"
    assert target["structural_number"] == paragraph
    assert target["structural_article_number"] == article
    assert target["year_candidate"] == "1989"
    assert target["resolution_status"] == "candidate"


def test_target_reference_does_not_invent_missing_year_or_parent_article():
    target = _target_reference_json(
        {
            "target_quote": "§ 11 de lei nº 3.882",
            "norma_candidate": {"tipo": "Lei", "numero": "3.882", "ano": ""},
            "device_type": "paragrafo",
            "device_number": "11",
        }
    )

    assert "year_candidate" in target and target["year_candidate"] is None
    assert "structural_article_number" not in target


def test_target_reference_can_use_year_suffix_from_enclosing_literal_item_only():
    target = _target_reference_json(
        {
            "target_quote": "§ 11 do art. 66 da Lei nº 3.882",
            "item_quote": "I – o § 11 do art. 66 e o §1º do art. 68 da Lei nº 3.882/89",
            "norma_candidate": {"tipo": "Lei", "numero": "3.882", "ano": ""},
            "device_type": "paragrafo",
            "device_number": "11",
        }
    )

    assert target["year_candidate"] == "1989"
    assert target["structural_article_number"] == "66"


def test_article_header_is_not_misclassified_as_an_amendment_target():
    text = (
        "Art. 1º Os artigos 2º, 3º e 16 da Lei 3.882/1989 passam a vigorar "
        "com as seguintes redações."
    )
    candidates = _single_device_amendment_candidates(
        [
            {
                "tipo": "artigo",
                "numero": "1º",
                "texto": text,
                "start_offset": 0,
                "end_offset": len(text),
                "structural_key": "artigo-1",
                "page_index": 1,
            }
        ]
    )
    assert [candidate["structural_article_number"] for candidate in candidates] == [
        "2º",
        "3º",
        "16",
    ]


def test_qualified_revocation_clause_inherits_action_to_listed_subdevices():
    intro_clause = "Revogam-se as disposições em contrário, em especial:"
    layout_header = (
        "ESTADO DO RIO GRANDE DO NORTE\nCÂMARA MUNICIPAL DE NATAL\n"
        "PALÁCIO PADRE MIGUELINHO"
    )
    intro = f"{intro_clause}\n\n--- Página 7 ---\n{layout_header}"
    item = "I - o § 11 do art. 66 e o §1º do art. 68 da Lei nº 3.882/89"
    source = f"{intro} {item}"
    intro_row = {
        "structural_key": "article-5",
        "parent_key": None,
        "tipo": "artigo",
        "numero": "5º",
        "texto": intro,
        "start_offset": 0,
        "end_offset": len(intro),
        "page_index": 7,
    }
    item_row = {
        "structural_key": "article-5-inciso-i",
        "parent_key": "article-5",
        "tipo": "inciso",
        "numero": "I",
        "texto": item,
        "start_offset": len(intro) + 1,
        "end_offset": len(source),
        "page_index": 7,
    }

    candidates = build_document_relation_preview([intro_row, item_row])

    assert [candidate["action"] for candidate in candidates] == ["REVOGA", "REVOGA"]
    assert {candidate["device_type"] for candidate in candidates} == {"paragrafo"}
    assert {candidate["device_number"] for candidate in candidates} == {"11", "1º"}
    assert all(candidate["action_quote"] == intro_clause[:-1] for candidate in candidates)


def test_acrescidos_is_detected_as_a_normative_addition_action():
    text = (
        "Art. 2º Ficam acrescidos os artigos 133-A, 133-B e 133-C à Lei nº "
        "3.882, de 11 de dezembro de 1989."
    )
    events = LegalNERExtractor().extract_events(text)
    targets = {
        event["referencia_numero"]
        for event in events
        if event["acao"] == "ADICIONA" and event["referencia_tipo"] == "artigo"
    }
    assert targets == {"133-A", "133-B", "133-C"}


def test_enumerated_incisos_are_not_misrepresented_as_revocation_of_whole_article():
    intro = "Revogam-se as disposições em contrário, em especial:"
    item = (
        "II – os incisos XV, XVI, XVII, XVIII, XIX, XX, XXI, XXII e XXIV "
        "do artigo 23 da Lei Complementar nº 141, de 28 de agosto de 2014"
    )
    source = f"{intro} {item}"
    devices = [
        {
            "structural_key": "article-5",
            "parent_key": None,
            "tipo": "artigo",
            "numero": "5º",
            "texto": intro,
            "start_offset": 0,
            "end_offset": len(intro),
            "page_index": 7,
        },
        {
            "structural_key": "article-5-inciso-ii",
            "parent_key": "article-5",
            "tipo": "inciso",
            "numero": "II",
            "texto": item,
            "start_offset": len(intro) + 1,
            "end_offset": len(source),
            "page_index": 7,
        },
    ]

    candidates = build_document_relation_preview(devices)

    assert [candidate["device_number"] for candidate in candidates] == [
        "XV", "XVI", "XVII", "XVIII", "XIX", "XX", "XXI", "XXII", "XXIV"
    ]
    assert all(candidate["device_type"] == "inciso" for candidate in candidates)
    assert all(candidate["structural_article_number"] == "23" for candidate in candidates)
    assert all(candidate["norma_candidate"]["numero"] == "141" for candidate in candidates)


def test_relation_preview_expands_a_parent_repeal_clause_without_approving_targets():
    devices = [
        {
            "structural_key": "art-260",
            "parent_key": None,
            "tipo": "artigo",
            "numero": "260",
            "texto": "Ficam revogados:",
            "page_index": 80,
        },
        {
            "structural_key": "inciso-i",
            "parent_key": "art-260",
            "tipo": "inciso",
            "numero": "I",
            "texto": "Lei Complementar nº 1.894 de 31 de dezembro de 1969;",
            "page_index": 80,
        },
        {
            "structural_key": "inciso-v",
            "parent_key": "art-260",
            "tipo": "inciso",
            "numero": "V",
            "texto": "Art. 21 da Lei Promulgada nº 275 de 12 de março de 2009;",
            "page_index": 81,
        },
    ]

    candidates = build_document_relation_preview(devices)

    assert len(candidates) == 2
    assert candidates[0]["action_quote"] == "Ficam revogados"
    assert candidates[0]["action_page"] == 80
    assert candidates[0]["norma_candidate"] == {
        "tipo": "Lei Complementar",
        "numero": "1.894",
        "ano": "1969",
    }
    assert candidates[1]["device_type"] == "artigo"
    assert candidates[1]["device_number"] == "21"
    assert candidates[1]["norma_candidate"]["tipo"] == "Lei Promulgada"
    assert candidates[1]["norma_candidate"]["numero"] == "275"
    assert candidates[1]["norma_candidate"]["ano"] == "2009"
    assert all(item["status"] == "candidate_unreviewed" for item in candidates)


def test_relation_preview_splits_multiple_normas_and_ignores_generic_repeal_clause():
    devices = [
        {
            "structural_key": "art-117",
            "parent_key": None,
            "tipo": "artigo",
            "numero": "117",
            "texto": "Revogam-se:",
            "page_index": 330,
        },
        {
            "structural_key": "inciso-ii",
            "parent_key": "art-117",
            "tipo": "inciso",
            "numero": "II",
            "texto": (
                "Leis Municipais nº 4.664 de 31 de julho de 1995, nº 5.273 de 20 de junho de "
                "2001, nº 4.912 de 10 de dezembro de 1997, nº 5.565 de 21 de junho de 2004, "
                "nº 221 de 22 de dezembro de 2022, nº 222 de 22 de dezembro de 2022, "
                "nº 223 de 22 de dezembro de 2022;"
            ),
            "page_index": 330,
        },
        {
            "structural_key": "inciso-iv",
            "parent_key": "art-117",
            "tipo": "inciso",
            "numero": "IV",
            "texto": "demais disposições em contrário.",
            "page_index": 331,
        },
    ]

    candidates = build_document_relation_preview(devices)

    assert [item["norma_candidate"]["numero"] for item in candidates] == [
        "4.664",
        "5.273",
        "4.912",
        "5.565",
        "221",
        "222",
        "223",
    ]
    assert all(item["action_device"] == "Artigo 117" for item in candidates)
    assert all(item["status"] == "candidate_unreviewed" for item in candidates)


def test_single_article_amendment_list_emits_exact_pending_candidates_without_ordinal_marker():
    article = (
        "Art. 1º Os artigos 2º, 3º, 16, 23, 25, 31, 38, 43, 43-A, 48, 50, 57, "
        "60, 64, 68, 86, 97, 98-A, 99, 100, 107, 112, 113, 131, 133, 143, "
        "146, 156, 160-B, 161 e 169 da Lei 3.882 de 11 de dezembro de 1989 "
        "passam a vigorar com as seguintes redações: “Art. 2º - ...”"
    )
    row = {
        "structural_key": "lc-217-art-1",
        "parent_key": None,
        "tipo": "artigo",
        "numero": "1º",
        "texto": article,
        "start_offset": 0,
        "end_offset": len(article),
        "page_index": 1,
    }

    candidates = build_document_relation_preview([row])

    assert len(candidates) == 31
    assert [candidate["device_number"] for candidate in candidates] == [
        "2º", "3º", "16", "23", "25", "31", "38", "43", "43-A", "48", "50",
        "57", "60", "64", "68", "86", "97", "98-A", "99", "100", "107", "112",
        "113", "131", "133", "143", "146", "156", "160-B", "161", "169",
    ]
    assert all(candidate["action"] == "ALTERA" for candidate in candidates)
    assert all(candidate["norma_candidate"] == {
        "tipo": "Lei", "numero": "3.882", "ano": "1989",
    } for candidate in candidates)
    assert all(candidate["item_device"] == "Artigo 1º" for candidate in candidates)
    assert all(candidate["status"] == "candidate_unreviewed" for candidate in candidates)
    assert all(
        article[candidate["action_start_offset"]:candidate["action_end_offset"]]
        == candidate["action_quote"]
        and article[candidate["target_start_offset"]:candidate["target_end_offset"]]
        == candidate["target_quote"]
        for candidate in candidates
    )


def test_single_article_amendment_preview_does_not_invent_missing_reference_year():
    article = "Art. 1º Os artigos 2º e 3º da Lei nº 3.882 passam a vigorar com redação nova."
    row = {
        "structural_key": "unresolved-amendment",
        "parent_key": None,
        "tipo": "artigo",
        "numero": "1º",
        "texto": article,
        "start_offset": 0,
        "end_offset": len(article),
        "page_index": 1,
    }

    assert build_document_relation_preview([row]) == []


@pytest.mark.django_db
def test_explicit_amendment_inside_article_becomes_one_exact_unreviewed_candidate():
    def digest(text):
        return hashlib.sha256(text.encode()).hexdigest()

    legal_text = (
        "Art. 118. O §2° do Art. 18 da lei complementar 208/2022 "
        "passa a vigorar com a seguinte redação:\n"
        "“Acrescer à Subzona de Uso Restrito da ZPA-1 os lotes indicados.”\n"
        "Art. 119. Esta Lei entra em vigor na data de sua publicação.\n"
    )
    document = DocumentoNormativo.objects.create(
        document_key=digest("direct-amendment-document"),
        source_kind=DocumentoNormativo.SourceKind.SAPL,
        source_ref="sapl:direct-amendment-document",
        role=DocumentoNormativo.Role.UNDETERMINED,
        original_filename="lei-complementar-261-2025.pdf",
        content_sha256=digest("direct-amendment-pdf"),
        official_url="https://sapl.natal.rn.leg.br/media/example.pdf",
        size_bytes=100,
        review_status=DocumentoNormativo.ReviewStatus.PENDING,
        metadata_json={
            "identity_candidate": {
                "type": "lei_complementar",
                "number": "261",
                "year": 2025,
                "jurisdiction": "BR-RN-NATAL",
            }
        },
    )
    extraction = ExtracaoDocumento.objects.create(
        documento=document,
        extractor_version="direct-amendment-v1",
        policy_fingerprint=digest("direct-amendment-policy"),
        text_version="legal-text-v1",
        raw_text=legal_text,
        legal_text=legal_text,
        page_count=1,
        page_map_json=[{"start": 0, "end": len(legal_text), "page": 1}],
        status=ExtracaoDocumento.Status.COMPLETE,
        extraction_sha256="",
    )

    candidates = extract_document_relation_candidates(extraction)

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate["action"] == "ALTERA"
    assert candidate["item_device"] == "Artigo 118"
    assert candidate["device_type"] == "paragrafo"
    assert candidate["device_number"] == "2º"
    assert candidate["structural_article_number"] == "18"
    assert candidate["norma_candidate"] == {
        "tipo": "lei complementar",
        "numero": "208",
        "ano": "2022",
    }
    assert "Acrescer à Subzona" in candidate["item_quote"]
    evidence = candidate["evidence_json"]
    assert legal_text[evidence["action_start_offset"]:evidence["action_end_offset"]] == evidence["action_quote"]
    assert legal_text[evidence["target_start_offset"]:evidence["target_end_offset"]] == evidence["target_quote"]
    assert evidence["item_quote"] == legal_text[
        evidence["item_start_offset"]:evidence["item_end_offset"]
    ]
    assert candidate["target_reference_json"]["structural_article_number"] == "18"
    assert candidate["target_reference_json"]["structural_number_raw"] == "2°"
    assert (
        candidate["target_reference_json"]["structural_number_resolution"]
        == "normalized_from_verified_pdf_glyph"
    )
    filtered = extract_document_relation_candidates(extraction, source_article="118")
    assert [item["item_device"] for item in filtered] == ["Artigo 118"]
    assert EventoNormativoCandidato.objects.filter(extracao=extraction).count() == 0


@pytest.mark.django_db
def test_persisted_document_relation_candidates_are_exact_immutable_and_idempotent():
    def digest(text):
        return hashlib.sha256(text.encode()).hexdigest()

    legal_text = (
        "Art. 260. Ficam revogados:\n"
        "I - Lei Complementar nº 1.894 de 31 de dezembro de 1969;\n"
        "II - Lei Promulgada nº 275 de 12 de março de 2009.\n"
    )
    document = DocumentoNormativo.objects.create(
        document_key=digest("candidate-relation-document"),
        source_kind=DocumentoNormativo.SourceKind.ARCHIVE,
        source_ref="archive:candidate-relation-document",
        role=DocumentoNormativo.Role.UNDETERMINED,
        original_filename="candidate-law.pdf",
        content_sha256=digest("candidate-relation-pdf"),
        size_bytes=100,
        review_status=DocumentoNormativo.ReviewStatus.PENDING,
    )
    extraction = ExtracaoDocumento.objects.create(
        documento=document,
        extractor_version="candidate-relation-test-v1",
        policy_fingerprint=digest("candidate-relation-policy"),
        text_version="legal-text-v1",
        raw_text=legal_text,
        legal_text=legal_text,
        page_count=1,
        page_map_json=[{"start": 0, "end": len(legal_text), "page": 1}],
        status=ExtracaoDocumento.Status.COMPLETE,
        extraction_sha256="",
    )

    preview = extract_document_relation_candidates(extraction)
    assert len(preview) == 2
    for item in preview:
        evidence = item["evidence_json"]
        assert (
            legal_text[evidence["action_start_offset"] : evidence["action_end_offset"]]
            == evidence["action_quote"]
        )
        assert (
            legal_text[evidence["target_start_offset"] : evidence["target_end_offset"]]
            == evidence["target_quote"]
        )
        assert item["target_reference_json"]["resolution_status"] == "candidate"

    assert persist_document_relation_candidates(extraction) == {
        "extraction_id": extraction.pk,
        "found": 2,
        "created": 2,
    }
    assert persist_document_relation_candidates(extraction) == {
        "extraction_id": extraction.pk,
        "found": 2,
        "created": 0,
    }
    candidate = EventoNormativoCandidato.objects.filter(extracao=extraction).first()
    candidate.target_text = "edited"
    with pytest.raises(ValidationError, match="imutáveis"):
        candidate.save()
    assert EventoNormativoCandidato.objects.filter(extracao=extraction).count() == 2


def test_inherited_article_repeal_keeps_target_law_identity_separate_from_article_number():
    legal_text = (
        "Art. 260. Ficam revogados:\n"
        "V - Art. 21 da Lei Promulgada n\ufffd 275 de 12 de março de 2009.\n"
    )
    extraction = SimpleNamespace(
        legal_text=legal_text,
        status=ExtracaoDocumento.Status.COMPLETE,
        page_map_json=[{"start": 0, "end": len(legal_text), "page": 1}],
        extraction_sha256=hashlib.sha256(legal_text.encode()).hexdigest(),
    )

    candidates = extract_document_relation_candidates(extraction)

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate["action"] == "REVOGA"
    assert candidate["norma_candidate"] == {
        "tipo": "Lei Promulgada",
        "numero": "275",
        "ano": "2009",
    }
    assert candidate["device_type"] == "artigo"
    assert candidate["device_number"] == "21"
    assert candidate["target_reference_json"]["number_candidate"] == "275"
    assert candidate["target_reference_json"]["structural_article_number"] == "21"
    assert candidate["target_reference_json"]["structural_number"] == "21"


@pytest.mark.django_db
def test_human_review_is_append_only_and_never_becomes_an_operational_graph_edge():
    def digest(text):
        return hashlib.sha256(text.encode()).hexdigest()

    legal_text = "Art. 260. Ficam revogados:\nI - Lei Complementar nº 1.894 de 31 de dezembro de 1969.\n"
    document = DocumentoNormativo.objects.create(
        document_key=digest("human-review-document"),
        source_kind=DocumentoNormativo.SourceKind.ARCHIVE,
        source_ref="archive:human-review-document",
        role=DocumentoNormativo.Role.UNDETERMINED,
        original_filename="candidate.pdf",
        content_sha256=digest("human-review-pdf"),
        size_bytes=100,
        review_status=DocumentoNormativo.ReviewStatus.PENDING,
    )
    extraction = ExtracaoDocumento.objects.create(
        documento=document,
        extractor_version="human-review-v1",
        policy_fingerprint=digest("human-review-policy"),
        text_version="legal-text-v1",
        raw_text=legal_text,
        legal_text=legal_text,
        page_count=1,
        page_map_json=[{"start": 0, "end": len(legal_text), "page": 1}],
        status=ExtracaoDocumento.Status.COMPLETE,
        extraction_sha256="",
    )
    persist_document_relation_candidates(extraction)
    candidate = EventoNormativoCandidato.objects.get(extracao=extraction)
    Norma.objects.create(
        tipo="Lei Complementar",
        numero="1894",
        ano=1969,
        identity_json={"jurisdiction": "BR-RN-NATAL", "synthetic_fixture": True},
    )
    target = Norma.objects.create(
        tipo="Lei",
        numero="1894",
        ano=1969,
        identity_json={"jurisdiction": "BR-RN-NATAL"},
    )
    assert candidate_target_normas(candidate) == []
    assert candidate_target_type_conflicts(candidate) == [target]

    target_document_candidates = []
    for suffix, candidate_type in (("exact", "lei_complementar"), ("conflict", "lei")):
        target_document_candidates.append(
            DocumentoNormativo.objects.create(
                document_key=digest(f"target-document-{suffix}"),
                source_kind=DocumentoNormativo.SourceKind.SAPL,
                source_ref=f"sapl:target-document-{suffix}",
                role=DocumentoNormativo.Role.UNDETERMINED,
                original_filename=f"target-{suffix}.pdf",
                content_sha256=digest(f"target-pdf-{suffix}"),
                size_bytes=100,
                review_status=DocumentoNormativo.ReviewStatus.PENDING,
                metadata_json={
                    "identity_candidate": {
                        "type": candidate_type,
                        "number": "1.894",
                        "year": 1969,
                        "jurisdiction": "BR-RN-NATAL",
                    }
                },
            )
        )
    DocumentoNormativo.objects.create(
        document_key=digest("target-document-synthetic"),
        source_kind=DocumentoNormativo.SourceKind.SAPL,
        source_ref="sapl:target-document-synthetic",
        role=DocumentoNormativo.Role.UNDETERMINED,
        original_filename="synthetic-target.pdf",
        content_sha256=digest("target-pdf-synthetic"),
        size_bytes=100,
        review_status=DocumentoNormativo.ReviewStatus.PENDING,
        metadata_json={
            "synthetic": True,
            "identity_candidate": {
                "type": "lei_complementar",
                "number": "1894",
                "year": 1969,
                "jurisdiction": "BR-RN-NATAL",
            },
        },
    )
    document_matches = candidate_target_documents(candidate)
    assert [item["document"] for item in document_matches] == target_document_candidates
    assert [item["type_matches"] for item in document_matches] == [True, False]

    actor = User.objects.create_user("candidate-reviewer", is_staff=True)
    actor.user_permissions.add(
        Permission.objects.get(
            content_type__app_label="legislation",
            codename="review_eventonormativocandidato",
        ),
        Permission.objects.get(
            content_type__app_label="legislation", codename="view_documentonormativo"
        ),
    )

    review = review_document_relation_candidate(
        candidate_id=candidate.pk,
        actor=actor,
        decision=RevisaoEventoNormativoCandidato.Decision.CONFIRM,
        reason="Conferi o inciso e a identidade da norma no documento-fonte.",
        expected_fingerprint=candidate.fingerprint,
        target_norma_id=None,
    )

    assert review.source_extraction_sha256 == extraction.extraction_sha256
    assert review.target_norma_id is None
    assert review.decision == RevisaoEventoNormativoCandidato.Decision.CONFIRM
    assert EventoAlteracao.objects.count() == 0
    assert document.accepted_extraction_id is None

    with pytest.raises(ValidationError, match="append-only"):
        review.reason = "alterado"
        review.save()
    assert candidate.revisoes.count() == 1


@pytest.mark.django_db
def test_exact_target_pdf_shows_unreviewed_article_preview_for_human_comparison():
    def digest(text):
        return hashlib.sha256(text.encode()).hexdigest()

    source_text = (
        "Art. 261. O art. 14 da Lei Complementar nº 208/2022 passa a vigorar "
        "com a seguinte redação.\n"
    )
    source_document = DocumentoNormativo.objects.create(
        document_key=digest("amending-source-document"),
        source_kind=DocumentoNormativo.SourceKind.ARCHIVE,
        source_ref="archive:amending-source-document",
        role=DocumentoNormativo.Role.UNDETERMINED,
        original_filename="lc-271-candidate.pdf",
        content_sha256=digest("amending-source-pdf"),
        size_bytes=100,
        review_status=DocumentoNormativo.ReviewStatus.PENDING,
    )
    source_extraction = ExtracaoDocumento.objects.create(
        documento=source_document,
        extractor_version="candidate-preview-v1",
        policy_fingerprint=digest("source-preview-policy"),
        text_version="legal-text-v1",
        raw_text=source_text,
        legal_text=source_text,
        page_count=1,
        page_map_json=[{"start": 0, "end": len(source_text), "page": 1}],
        status=ExtracaoDocumento.Status.COMPLETE,
        extraction_sha256="",
    )
    persist_document_relation_candidates(source_extraction)
    candidate = EventoNormativoCandidato.objects.get(extracao=source_extraction)
    reference = candidate.target_reference_json
    assert reference["structural_article_number"] == "14"

    target_text = (
        "Art. 14. Redação anterior do dispositivo para conferência.\n"
        "Art. 15. Dispositivo seguinte que não deve aparecer na prévia.\n"
    )
    target_document = DocumentoNormativo.objects.create(
        document_key=digest("target-law-document"),
        source_kind=DocumentoNormativo.SourceKind.SAPL,
        source_ref="sapl:target-law-document",
        role=DocumentoNormativo.Role.ORIGINAL,
        original_filename="lc208-2022.pdf",
        content_sha256=digest("target-law-pdf"),
        size_bytes=100,
        review_status=DocumentoNormativo.ReviewStatus.PENDING,
        metadata_json={
            "identity_candidate": {
                "type": "Lei Complementar",
                "number": "208",
                "year": 2022,
                "jurisdiction": "BR-RN-NATAL",
            }
        },
    )
    ExtracaoDocumento.objects.create(
        documento=target_document,
        extractor_version="target-preview-v1",
        policy_fingerprint=digest("target-preview-policy"),
        text_version="legal-text-v1",
        raw_text=target_text,
        legal_text=target_text,
        page_count=12,
        page_map_json=[{"start": 0, "end": len(target_text), "page": 9}],
        status=ExtracaoDocumento.Status.COMPLETE,
        extraction_sha256="",
    )

    matches = candidate_target_documents(candidate)
    assert len(matches) == 1
    preview = matches[0]["device_preview"]
    assert preview["article_number"] == "14"
    assert preview["text"].startswith("Art. 14.")
    assert "Art. 15" not in preview["text"]
    assert preview["page_index"] == 9
    assert preview["review_status"] == "candidate_unreviewed"
    assert target_document.review_status == DocumentoNormativo.ReviewStatus.PENDING
    assert EventoAlteracao.objects.count() == 0


@pytest.mark.django_db
def test_long_relation_quote_keeps_full_evidence_and_bounded_display_columns():
    def digest(value):
        return hashlib.sha256(value.encode()).hexdigest()

    target_quote = "Lei Complementar nº 12/2000; " + ("norma enumerada; " * 50)
    action_quote = "Ficam alteradas as normas abaixo"
    legal_text = f"Art. 1º {action_quote}: {target_quote}"
    document = DocumentoNormativo.objects.create(
        document_key=digest("long-relation-document"),
        source_kind=DocumentoNormativo.SourceKind.ARCHIVE,
        source_ref="archive:long-relation-document",
        role=DocumentoNormativo.Role.ORIGINAL,
        original_filename="long-relation.pdf",
        content_sha256=digest("long-relation-pdf"),
        size_bytes=100,
        review_status=DocumentoNormativo.ReviewStatus.PENDING,
    )
    extraction = ExtracaoDocumento.objects.create(
        documento=document,
        extractor_version="long-relation-v1",
        policy_fingerprint=digest("long-relation-policy"),
        text_version="legal-text-v1",
        raw_text=legal_text,
        legal_text=legal_text,
        page_count=1,
        status=ExtracaoDocumento.Status.COMPLETE,
        extraction_sha256="",
    )
    action_start = legal_text.index(action_quote)
    target_start = legal_text.index(target_quote)
    item = {
        "source_structural_key": "article-1",
        "item_device": "Artigo 1º",
        "action": "ALTERA",
        "action_quote": action_quote,
        "target_quote": target_quote,
        "action_start_offset": action_start,
        "action_end_offset": action_start + len(action_quote),
        "target_start_offset": target_start,
        "target_end_offset": target_start + len(target_quote),
        "item_quote": legal_text,
        "item_start_offset": 0,
        "item_end_offset": len(legal_text),
        "action_page": 1,
        "target_page": 1,
        "norma_candidate": {"tipo": "Lei Complementar", "numero": "12", "ano": "2000"},
        "device_type": "act",
        "device_number": "",
        "fingerprint": digest("long-relation-candidate"),
        "evidence_json": {
            "schema_version": 1,
            "status": "candidate_unreviewed",
            "source_extraction_sha256": extraction.extraction_sha256,
            "action_quote": action_quote,
            "action_start_offset": action_start,
            "action_end_offset": action_start + len(action_quote),
            "target_quote": target_quote,
            "target_start_offset": target_start,
            "target_end_offset": target_start + len(target_quote),
            "item_quote": legal_text,
            "item_start_offset": 0,
            "item_end_offset": len(legal_text),
            "item_device": "Artigo 1º",
            "action_device": "Artigo 1º",
            "action_page": 1,
            "target_page": 1,
        },
        "target_reference_json": {
            "schema_version": 1,
            "resolution_status": "candidate",
            "type_candidate": "Lei Complementar",
            "number_candidate": "12",
            "year_candidate": "2000",
            "structural_type": "act",
            "structural_number": "",
        },
    }

    with patch(
        "src.apps.ingestion.document_relation_candidates.extract_document_relation_candidates",
        return_value=[item, dict(item)],
    ):
        result = persist_document_relation_candidates(extraction)

    candidate = EventoNormativoCandidato.objects.get(extracao=extraction)
    assert len(target_quote) > 500
    assert result == {"extraction_id": extraction.pk, "found": 2, "created": 1}
    assert candidate.target_text == target_quote[:500]
    assert candidate.evidence_json["target_quote"] == target_quote
    assert candidate.evidence_json["target_start_offset"] == target_start
