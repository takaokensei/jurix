from datetime import date
from types import SimpleNamespace
from unittest.mock import patch

from django.test import override_settings

from src.apps.legislation.serializers import (
    _legacy_archive_document_id,
    serialize_chat_message,
    serialize_citation_sources,
    serialize_dispositivo_source,
)


def test_source_serializer_survives_broken_norma_relation():
    class BrokenDispositivo:
        id = 42
        texto = "Trecho preservado"

        @property
        def norma(self):
            raise RuntimeError("relação indisponível")

        def get_full_identifier(self):
            return "Art. 1º"

    result = serialize_dispositivo_source({"dispositivo": BrokenDispositivo()})

    assert result["id"] == 42
    assert result["full_text"] == "Trecho preservado"
    assert result["source_url"] is None
    assert result["temporal_status"] == "data_indeterminada"


def test_cached_source_coerces_legacy_non_string_text():
    result = serialize_dispositivo_source({"id": 7, "text": 12345})

    assert result["full_text"] == "12345"
    assert result["text"] == "12345"


def test_cached_source_builds_readable_stable_citation_identity():
    result = serialize_citation_sources(
        [
            {
                "id": 81,
                "norma_id": 22,
                "norma_ref": "Lei nº 8.206/2026",
                "dispositivo_ref": "Art. 2º > Inciso I",
                "text": "Regra do inciso.",
            }
        ]
    )[0]

    assert result["citation_id"] == "jurix:norma:22:dispositivo:81"
    assert result["citation_index"] == 1
    assert result["citation_label"] == "Lei nº 8.206/2026, Art. 2º, inciso I"


def test_explicit_reference_match_kind_survives_cached_source_serialization():
    result = serialize_dispositivo_source(
        {
            "id": 7,
            "norma_ref": "Lei nº 8.206/2026",
            "dispositivo_ref": "Art. 1º",
            "text": "Texto exato.",
            "match_kind": "explicit_reference",
            "similarity_score": 0,
        }
    )

    assert result["match_kind"] == "explicit_reference"
    assert result["similarity_score"] == 0


def test_missing_match_kind_remains_compatible_with_legacy_sources():
    result = serialize_dispositivo_source({"id": 8, "text": "Fonte antiga."})

    assert result["match_kind"] is None


def test_local_archive_source_gets_an_internal_document_pdf_link():
    result = serialize_dispositivo_source({
        "id": "qa:article-1",
        "source_id": "00000000-0000-0000-0000-000000000001",
        "evidence_scope": "isolated_qa_archive",
        "pdf_url": None,
        "sapl_url": None,
        "text": "Trecho extraído.",
    })

    assert result["local_pdf_url"] == (
        "/normas/documentos/00000000-0000-0000-0000-000000000001/pdf/"
    )
    assert result["source_id"] == "00000000-0000-0000-0000-000000000001"


def test_non_archive_source_cannot_get_local_archive_pdf_link():
    result = serialize_dispositivo_source({
        "source_id": "00000000-0000-0000-0000-000000000001",
        "evidence_scope": "production_corpus",
    })

    assert result["local_pdf_url"] is None
    assert result["source_id"] is None


def test_legacy_archive_source_citation_rewrites_outdated_test_label():
    source = {
        "evidence_scope": "isolated_qa_archive",
        "norma_ref": "Lei Complementar nº 120/2010",
        "dispositivo_ref": "Art. 3º",
        "citation_label": "Lei Complementar nº 120/2010, Art. 3º (PDF de teste)",
        "source_type": "PDF importado — corpus de teste, não validado",
        "contribution": "Trecho extraído do PDF; não validado juridicamente",
        "full_text": "O PCCV-SAÚDE tem como princípios: trecho jurídico arquivado para validação.",
    }
    with patch(
        "src.apps.legislation.serializers._legacy_archive_document_id",
        return_value="00000000-0000-0000-0000-000000000001",
    ):
        result = serialize_dispositivo_source(source)

    assert result["citation_label"] == "Lei Complementar nº 120/2010, Art. 3º"
    assert result["source_type"] == "Acervo histórico local — extração pendente de revisão"
    assert result["contribution"] == (
        "Trecho da extração do PDF arquivado; transcrição pendente de revisão"
    )
    assert result["local_pdf_url"] == (
        "/normas/documentos/00000000-0000-0000-0000-000000000001/pdf/"
    )


@override_settings(NORMATIVE_ARCHIVE_ASSISTANT_ENABLED=True)
def test_legacy_archive_pdf_recovery_requires_one_identity_and_text_match():
    from src.apps.legislation.document_models import ExtracaoDocumento

    extracted_text = "Art. 3º O PCCV-SAÚDE tem como princípios a valorização profissional e a qualidade pública."
    extraction = SimpleNamespace(
        status=ExtracaoDocumento.Status.COMPLETE,
        legal_text=extracted_text,
    )
    document = SimpleNamespace(
        public_id="00000000-0000-0000-0000-000000000001",
        extracoes=SimpleNamespace(
            order_by=lambda *_args: SimpleNamespace(first=lambda: extraction)
        ),
    )
    source = {"full_text": "O PCCV-SAÚDE tem como princípios a valorização profissional e a qualidade pública."}

    with patch("src.apps.legislation.document_models.DocumentoNormativo.objects.filter") as query:
        query.return_value.order_by.return_value.__getitem__.return_value = [document]
        result = _legacy_archive_document_id(source, "Lei Complementar nº 120/2010")

    assert result == "00000000-0000-0000-0000-000000000001"
    assert query.call_args.kwargs["metadata_json__identity_key"] == (
        "BR-RN-NATAL|lei_complementar|municipal_lc|120|2010"
    )


def test_restored_chat_sources_use_the_current_archive_citation_contract():
    message = SimpleNamespace(
        id=9,
        role="assistant",
        content="Trecho citado [[1]].",
        sources_json=[{
            "id": "stable-device-id",
            "norma_ref": "Lei Complementar nº 120/2010",
            "dispositivo_ref": "Art. 3º",
            "citation_label": "Lei Complementar nº 120/2010, Art. 3º (PDF de teste)",
            "source_type": "PDF importado — corpus de teste, não validado",
            "contribution": "Trecho extraído do PDF; não validado juridicamente",
            "evidence_scope": "isolated_qa_archive",
            "full_text": "O PCCV-SAÚDE tem como princípios a valorização profissional e a qualidade pública.",
        }],
        metadata_json={},
        created_at=None,
    )
    with patch(
        "src.apps.legislation.serializers._legacy_archive_document_id",
        return_value="00000000-0000-0000-0000-000000000001",
    ):
        payload = serialize_chat_message(message)

    restored_source = payload["sources"][0]
    assert restored_source["local_pdf_url"] == (
        "/normas/documentos/00000000-0000-0000-0000-000000000001/pdf/"
    )
    assert restored_source["citation_label"] == "Lei Complementar nº 120/2010, Art. 3º"
    assert restored_source["source_type"] == "Acervo histórico local — extração pendente de revisão"


def test_explicit_reference_match_kind_survives_model_source_serialization():
    norma = SimpleNamespace(
        id=4,
        tipo="Lei",
        numero="8206",
        ano=2026,
        pdf_url="https://sapl.natal.rn.leg.br/test.pdf",
        sapl_url=None,
        sapl_id=4,
        data_publicacao=date(2026, 1, 1),
        data_vigencia=None,
        get_tipo_display_name=lambda: "Lei",
    )
    dispositivo = SimpleNamespace(
        id=9,
        norma=norma,
        texto="Texto legal.",
        get_full_identifier=lambda: "Art. 1º",
    )

    result = serialize_dispositivo_source(
        {"dispositivo": dispositivo, "match_kind": "explicit_reference"}
    )

    assert result["match_kind"] == "explicit_reference"
    assert result["dispositivo_id"] == 9


def test_synthetic_qa_document_is_explicitly_marked_in_citation_dto():
    norma = SimpleNamespace(
        id=4,
        tipo="Lei",
        numero="9001",
        ano=2020,
        pdf_url=None,
        sapl_url=None,
        sapl_id=None,
        data_publicacao=None,
        data_vigencia=None,
        documento_base=SimpleNamespace(metadata_json={"synthetic": True}),
        get_tipo_display_name=lambda: "Lei",
    )
    dispositivo = SimpleNamespace(
        id=9,
        norma=norma,
        texto="Fixture de teste.",
        get_full_identifier=lambda: "Art. 1º",
    )

    result = serialize_dispositivo_source({"dispositivo": dispositivo})

    assert result["synthetic_fixture"] is True
    assert result["source_type"] == "Fixture sintética de QA — não representa legislação real"
