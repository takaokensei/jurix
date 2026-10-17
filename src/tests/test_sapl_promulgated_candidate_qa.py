from __future__ import annotations

from types import SimpleNamespace

import pytest
from django.test import override_settings

from src.apps.ingestion.management.commands import stage_sapl_normative_candidate_qa as staging
from src.apps.ingestion.management.commands.extract_sapl_normative_candidate_qa import (
    _quality_summary,
)
from src.apps.legislation.models import Norma

OFFICIAL_PDF = (
    "https://sapl.natal.rn.leg.br/media/sapl/public/normajuridica/2022/1160/"
    "pdn_-_lc_208_2022.pdf"
)
ORDINARY_1894_PDF = (
    "https://sapl.natal.rn.leg.br/media/sapl/public/normajuridica/1969/3666/"
    "lei01894-69.pdf"
)
LAW_4885_PDF = (
    "https://sapl.natal.rn.leg.br/media/sapl/public/normajuridica/1997/6817/"
    "lei04885-97.pdf"
)
LAW_8219_PDF = (
    "https://sapl.natal.rn.leg.br/media/sapl/public/normajuridica/2026/9406/"
    "lei_no_8.219_2026.pdf"
)


def _record(**changes):
    record = {
        "id": 1160,
        "tipo": 2,
        "numero": "208",
        "ano": 2022,
        "complemento": True,
        "texto_integral": OFFICIAL_PDF,
        "data": "2022-03-07",
        "data_publicacao": "2022-03-08",
        "veiculo_publicacao": "DOM",
        "ementa": "Dispõe sobre o Plano Diretor de Natal, e dá outras providências.",
        # A proposal/matter id is present in the upstream record but must not be
        # imported into the normative candidate or RAG.
        "materia": 14618,
        "autores": [{"id": 123}],
        "ip": "192.0.2.1",
    }
    record.update(changes)
    return record


def _lc261_record(**changes):
    record = _record(
        id=8823,
        numero="261",
        ano=2025,
        complemento=False,
        texto_integral=(
            "https://sapl.natal.rn.leg.br/media/sapl/public/normajuridica/2025/8823/"
            "lei_complementar_no_261_2025.pdf"
        ),
        data="2025-06-17",
        data_publicacao="2025-07-04",
        ementa="Dispõe sobre as prescrições urbanísticas e ambientais das ZPA.",
    )
    record.update(changes)
    return record


def _lc258_record(**changes):
    record = _record(
        id=4052,
        numero="258",
        ano=2024,
        complemento=False,
        texto_integral=(
            "https://sapl.natal.rn.leg.br/media/sapl/public/normajuridica/2024/4052/"
            "lei_complementar_no_258_2024.pdf"
        ),
        data="2024-12-26",
        data_publicacao="2024-12-27",
        ementa="Institui o Código de Obras e Edificações do município de Natal.",
    )
    record.update(changes)
    return record


def _lp562_record(**changes):
    record = _record(
        id=254,
        tipo=9,
        numero="562",
        ano=2018,
        complemento=False,
        texto_integral=(
            "https://sapl.natal.rn.leg.br/media/sapl/public/normajuridica/2018/254/"
            "lp_562.18.pdf"
        ),
        data="2018-09-14",
        data_publicacao="2018-09-18",
        ementa=(
            "Dispõe sobre a obrigatoriedade de vistoria técnica e manutenção "
            "preventiva e periódica das edificações em Natal."
        ),
    )
    record.update(changes)
    return record


def _lc198_record(**changes):
    record = _record(
        id=925,
        numero="198",
        ano=2021,
        complemento=False,
        texto_integral=(
            "https://sapl.natal.rn.leg.br/media/sapl/public/normajuridica/2021/925/"
            "plc_006.21-convertido.pdf"
        ),
        data="2021-11-12",
        data_publicacao="2021-12-20",
        ementa=(
            "Estabelece a obrigatoriedade de instalação de placa informativa sobre "
            "licenciamento em obras e empreendimentos no município de Natal."
        ),
    )
    record.update(changes)
    return record


def _ordinary_1894_record(**changes):
    record = _record(
        id=3666,
        tipo=1,
        numero="1894",
        ano=1969,
        complemento=False,
        texto_integral=ORDINARY_1894_PDF,
        data="1969-12-25",
        data_publicacao=None,
        veiculo_publicacao="",
        ementa="",
    )
    record.update(changes)
    return record


def _law_4885_record(**changes):
    record = _record(
        id=6817,
        tipo=1,
        numero="4885",
        ano=1997,
        complemento=False,
        texto_integral=LAW_4885_PDF,
        data="1997-10-07",
        data_publicacao="1997-10-08",
        veiculo_publicacao="DOM",
        ementa=(
            "Dispõe sobre a exigência de Relatório de Impacto sobre o Tráfego Urbano "
            "para empreendimentos novos, ampliações de empreendimentos existentes e "
            "alterações de usos de imóveis, e dá outras providências."
        ),
    )
    record.update(changes)
    return record


def _law_8219_record(**changes):
    record = _record(
        id=9406,
        tipo=1,
        numero="8219",
        ano=2026,
        complemento=False,
        texto_integral=LAW_8219_PDF,
        data="2026-10-14",
        data_publicacao="2026-10-14",
        veiculo_publicacao="",
        ementa="Lei promulgada usada para testar a conferência de identidade do candidato.",
    )
    record.update(changes)
    return record


@pytest.mark.django_db
def test_existing_8219_registry_conflicts_are_reported_without_mutation(monkeypatch, tmp_path):
    _qa_env(monkeypatch, tmp_path / "qa")
    _client(monkeypatch, _law_8219_record())
    norma = Norma.objects.create(
        sapl_id=9406,
        tipo="Lei",
        numero="8219",
        ano=2026,
        data_publicacao="2026-10-14",
        pdf_url="http://sapl.natal.rn.leg.br/media/sapl/public/normajuridica/2026/9406/lei_no_8.219_2026.pdf",
        status=Norma.Status.PENDING,
        identity_key="legacy-sapl-9406",
        identity_json={},
    )
    before = (norma.tipo, norma.pdf_url, norma.identity_key, norma.identity_json)

    with override_settings(QA_ROOT=tmp_path / "qa", NORMATIVE_ARCHIVE_ENABLED=True):
        result = staging.stage_sapl_normative_candidate(
            sapl_id=9406, apply=False, inspect_existing=True
        )

    norma.refresh_from_db()
    assert result["eligible_to_stage"] is False
    assert result["existing_norma_conflicts"] == ["identity_key", "tipo", "pdf_url"]
    assert (norma.tipo, norma.pdf_url, norma.identity_key, norma.identity_json) == before


def _client(monkeypatch, payload=None):
    client = SimpleNamespace(
        fetch_norma_by_id=lambda sapl_id: payload or _record(),
        _validated_sapl_pdf_url=lambda url: url,
        fingerprint_pdf=lambda url: "sha256:" + ("a" * 64),
        get_public_norma_url=lambda sapl_id: f"https://sapl.natal.rn.leg.br/norma/{sapl_id}",
        close=lambda: None,
    )
    monkeypatch.setattr(staging, "SaplAPIClient", lambda **kwargs: client)
    return client


def _qa_env(monkeypatch, qa_root):
    monkeypatch.setenv("JURIX_QA_ONLY", "1")
    monkeypatch.setenv("DJANGO_SETTINGS_MODULE", "config.settings_normative_qa")
    monkeypatch.setenv("JURIX_QA_ROOT", str(qa_root))


def test_sapl_candidate_dry_run_is_explicitly_promulgated_and_omits_matter(monkeypatch, tmp_path):
    _qa_env(monkeypatch, tmp_path / "qa")
    client = _client(monkeypatch)

    with override_settings(QA_ROOT=tmp_path / "qa", NORMATIVE_ARCHIVE_ENABLED=True):
        _raw, _url, candidate = staging._validated_record(client, 1160)
        result = staging.stage_sapl_normative_candidate(sapl_id=1160, apply=False)

    assert candidate["safe_metadata"]["id"] == 1160
    assert "materia" not in candidate["safe_metadata"]
    assert "autores" not in candidate["safe_metadata"]
    assert "ip" not in candidate["safe_metadata"]
    assert result["mode"] == "dry-run"
    assert result["will_create_norma"] is True
    assert result["will_create_pending_pdf_candidate"] is True
    assert result["will_accept_text"] is False
    assert result["will_create_consolidation"] is False
    assert result["matter_metadata_imported"] is False


def test_sapl_candidate_rejects_non_allowlisted_or_mismatched_record(monkeypatch, tmp_path):
    _qa_env(monkeypatch, tmp_path / "qa")
    _client(monkeypatch, _record(tipo=1))

    with override_settings(QA_ROOT=tmp_path / "qa", NORMATIVE_ARCHIVE_ENABLED=True):
        with pytest.raises(ValueError, match="diverge"):
            staging.stage_sapl_normative_candidate(sapl_id=1160)
        with pytest.raises(ValueError, match="explicitamente autorizados"):
            staging.stage_sapl_normative_candidate(sapl_id=16180)


def test_lc261_candidate_requires_exact_promulgated_record_and_publication_date(
    monkeypatch, tmp_path
):
    _qa_env(monkeypatch, tmp_path / "qa")
    client = _client(monkeypatch, _lc261_record())

    with override_settings(QA_ROOT=tmp_path / "qa", NORMATIVE_ARCHIVE_ENABLED=True):
        _raw, pdf_url, candidate = staging._validated_record(client, 8823)
        result = staging.stage_sapl_normative_candidate(sapl_id=8823, apply=False)

    assert pdf_url.endswith("/2025/8823/lei_complementar_no_261_2025.pdf")
    assert candidate["identity"].identity_json["number"] == "261"
    assert candidate["publication_date"].isoformat() == "2025-07-04"
    assert "materia" not in candidate["safe_metadata"]
    assert result["mode"] == "dry-run"
    assert result["will_accept_text"] is False
    assert result["will_create_consolidation"] is False

    client = _client(monkeypatch, _lc261_record(data_publicacao="2025-07-05"))
    with override_settings(QA_ROOT=tmp_path / "qa", NORMATIVE_ARCHIVE_ENABLED=True):
        with pytest.raises(ValueError, match="data de publicação"):
            staging._validated_record(client, 8823)


def test_lc258_candidate_requires_exact_promulgated_record_and_publication_date(
    monkeypatch, tmp_path
):
    _qa_env(monkeypatch, tmp_path / "qa")
    client = _client(monkeypatch, _lc258_record())

    with override_settings(QA_ROOT=tmp_path / "qa", NORMATIVE_ARCHIVE_ENABLED=True):
        _raw, pdf_url, candidate = staging._validated_record(client, 4052)
        result = staging.stage_sapl_normative_candidate(sapl_id=4052, apply=False)

    assert pdf_url.endswith("/2024/4052/lei_complementar_no_258_2024.pdf")
    assert candidate["identity"].identity_json["number"] == "258"
    assert candidate["publication_date"].isoformat() == "2024-12-27"
    assert "materia" not in candidate["safe_metadata"]
    assert result["mode"] == "dry-run"
    assert result["will_accept_text"] is False
    assert result["will_create_consolidation"] is False

    client = _client(monkeypatch, _lc258_record(data_publicacao="2024-12-28"))
    with override_settings(QA_ROOT=tmp_path / "qa", NORMATIVE_ARCHIVE_ENABLED=True):
        with pytest.raises(ValueError, match="data de publicação"):
            staging._validated_record(client, 4052)


def test_lei_promulgada_562_candidate_uses_its_own_series_and_omits_matter(
    monkeypatch, tmp_path
):
    _qa_env(monkeypatch, tmp_path / "qa")
    client = _client(monkeypatch, _lp562_record())

    with override_settings(QA_ROOT=tmp_path / "qa", NORMATIVE_ARCHIVE_ENABLED=True):
        _raw, pdf_url, candidate = staging._validated_record(client, 254)
        result = staging.stage_sapl_normative_candidate(sapl_id=254, apply=False)

    assert pdf_url.endswith("/2018/254/lp_562.18.pdf")
    assert candidate["identity"].identity_json["series"] == "municipal_lp"
    assert candidate["identity"].identity_json["number"] == "562"
    assert candidate["publication_date"].isoformat() == "2018-09-18"
    assert "materia" not in candidate["safe_metadata"]
    assert "autores" not in candidate["safe_metadata"]
    assert result["mode"] == "dry-run"
    assert result["will_create_pending_pdf_candidate"] is True
    assert result["will_accept_text"] is False
    assert result["will_create_consolidation"] is False
    assert result["matter_metadata_imported"] is False

    client = _client(monkeypatch, _lp562_record(tipo=2))
    with override_settings(QA_ROOT=tmp_path / "qa", NORMATIVE_ARCHIVE_ENABLED=True):
        with pytest.raises(ValueError, match="diverge"):
            staging._validated_record(client, 254)


def test_lc198_candidate_requires_exact_promulgated_identity_and_date(monkeypatch, tmp_path):
    _qa_env(monkeypatch, tmp_path / "qa")
    client = _client(monkeypatch, _lc198_record())

    with override_settings(QA_ROOT=tmp_path / "qa", NORMATIVE_ARCHIVE_ENABLED=True):
        _raw, pdf_url, candidate = staging._validated_record(client, 925)
        result = staging.stage_sapl_normative_candidate(sapl_id=925, apply=False)

    assert pdf_url.endswith("/2021/925/plc_006.21-convertido.pdf")
    assert candidate["identity"].identity_json["type"] == "lei_complementar"
    assert candidate["identity"].identity_json["number"] == "198"
    assert candidate["publication_date"].isoformat() == "2021-12-20"
    assert "materia" not in candidate["safe_metadata"]
    assert result["mode"] == "dry-run"
    assert result["will_create_pending_pdf_candidate"] is True
    assert result["will_accept_text"] is False
    assert result["will_create_consolidation"] is False

    client = _client(monkeypatch, _lc198_record(tipo=1))
    with override_settings(QA_ROOT=tmp_path / "qa", NORMATIVE_ARCHIVE_ENABLED=True):
        with pytest.raises(ValueError, match="diverge"):
            staging._validated_record(client, 925)

    client = _client(monkeypatch, _lc198_record(data_publicacao="2021-12-21"))
    with override_settings(QA_ROOT=tmp_path / "qa", NORMATIVE_ARCHIVE_ENABLED=True):
        with pytest.raises(ValueError, match="data de publicação"):
            staging._validated_record(client, 925)


def test_ordinary_1894_candidate_preserves_missing_publication_date(monkeypatch, tmp_path):
    _qa_env(monkeypatch, tmp_path / "qa")
    client = _client(monkeypatch, _ordinary_1894_record())

    with override_settings(QA_ROOT=tmp_path / "qa", NORMATIVE_ARCHIVE_ENABLED=True):
        _raw, pdf_url, candidate = staging._validated_record(client, 3666)
        result = staging.stage_sapl_normative_candidate(sapl_id=3666, apply=False)

    assert pdf_url == ORDINARY_1894_PDF
    assert candidate["identity"].identity_json["type"] == "lei"
    assert candidate["identity"].identity_json["series"] == "municipal_lo"
    assert candidate["identity"].identity_json["number"] == "1894"
    assert candidate["safe_metadata"]["data_publicacao"] is None
    assert candidate["publication_date"] is None
    assert result["mode"] == "dry-run"
    assert result["publication_date"] is None
    assert result["will_accept_text"] is False
    assert result["will_create_consolidation"] is False
    assert result["matter_metadata_imported"] is False


def test_law_4885_candidate_is_exact_promulgated_record_and_stays_pending(
    monkeypatch, tmp_path
):
    _qa_env(monkeypatch, tmp_path / "qa")
    client = _client(monkeypatch, _law_4885_record())

    with override_settings(QA_ROOT=tmp_path / "qa", NORMATIVE_ARCHIVE_ENABLED=True):
        _raw, pdf_url, candidate = staging._validated_record(client, 6817)
        result = staging.stage_sapl_normative_candidate(sapl_id=6817, apply=False)

    assert pdf_url == LAW_4885_PDF
    assert candidate["identity"].identity_json["type"] == "lei"
    assert candidate["identity"].identity_json["series"] == "municipal_lo"
    assert candidate["identity"].identity_json["number"] == "4885"
    assert candidate["identity"].identity_json["year"] == 1997
    assert candidate["publication_date"].isoformat() == "1997-10-08"
    assert "materia" not in candidate["safe_metadata"]
    assert "autores" not in candidate["safe_metadata"]
    assert result["mode"] == "dry-run"
    assert result["will_create_pending_pdf_candidate"] is True
    assert result["will_accept_text"] is False
    assert result["will_create_consolidation"] is False
    assert result["matter_metadata_imported"] is False

    client = _client(monkeypatch, _law_4885_record(tipo=2))
    with override_settings(QA_ROOT=tmp_path / "qa", NORMATIVE_ARCHIVE_ENABLED=True):
        with pytest.raises(ValueError, match="diverge"):
            staging._validated_record(client, 6817)

    client = _client(monkeypatch, _ordinary_1894_record(tipo=2))
    with override_settings(QA_ROOT=tmp_path / "qa", NORMATIVE_ARCHIVE_ENABLED=True):
        with pytest.raises(ValueError, match="diverge"):
            staging._validated_record(client, 3666)

    client = _client(monkeypatch, _ordinary_1894_record(data_publicacao="não é data"))
    with override_settings(QA_ROOT=tmp_path / "qa", NORMATIVE_ARCHIVE_ENABLED=True):
        with pytest.raises(ValueError, match="formato inválido"):
            staging._validated_record(client, 3666)


def test_sapl_extraction_quality_summary_exposes_only_bounded_counts():
    extraction = SimpleNamespace(
        quality_json={
            "page_methods": {"native": 91, "ocr": 2, "blank": 1, "unreadable": 1},
            "unreadable_pages": [94],
            "ocr_pages_attempted": [94, 95],
            "ocr_budget_skipped_pages": [],
        },
        metadata_candidates_json={"layout_tables": {"candidate_count": 3}},
    )

    assert _quality_summary(extraction) == {
        "native_pages": 91,
        "ocr_pages": 2,
        "blank_pages": 1,
        "unreadable_pages": 1,
        "ocr_attempted_pages": 2,
        "ocr_budget_skipped_pages": 0,
        "layout_table_candidates": 3,
    }


@pytest.mark.django_db
def test_sapl_candidate_apply_creates_only_pending_norma_and_pdf_candidate(
    monkeypatch, tmp_path
):
    qa_root = tmp_path / "qa"
    _qa_env(monkeypatch, qa_root)
    _client(monkeypatch)
    fake_document = SimpleNamespace(
        public_id="b5e5d2d8-9749-4a54-96a9-10dfb2b0aab0",
        review_status="pending",
        accepted_extraction_id=None,
        norma_id=1,
        ReviewStatus=SimpleNamespace(PENDING="pending"),
    )
    stage_calls = []

    def fake_stage(**kwargs):
        stage_calls.append(kwargs)
        fake_document.norma_id = kwargs["norma"].pk
        return fake_document, True

    monkeypatch.setattr(
        "src.apps.ingestion.sapl_document_sync.stage_sapl_pdf_candidate", fake_stage
    )
    with override_settings(QA_ROOT=qa_root, NORMATIVE_ARCHIVE_ENABLED=True):
        result = staging.stage_sapl_normative_candidate(sapl_id=1160, apply=True)

    norma = Norma.objects.get(sapl_id=1160)
    assert result["mode"] == "applied"
    assert result["norma_created"] is True
    assert result["norma_status"] == Norma.Status.PENDING
    assert result["review_status"] == "pending"
    assert result["text_accepted"] is False
    assert result["norma_linked_as_base"] is False
    assert result["matter_metadata_imported"] is False
    assert norma.documento_base_id is None
    assert norma.texto_original == ""
    assert norma.texto_consolidado == ""
    assert "materia" not in norma.sapl_metadata
    assert len(stage_calls) == 1
    assert stage_calls[0]["pdf_url"] == OFFICIAL_PDF


@pytest.mark.django_db
def test_lei_promulgada_apply_preserves_type_and_remains_unaccepted(
    monkeypatch, tmp_path
):
    qa_root = tmp_path / "qa"
    _qa_env(monkeypatch, qa_root)
    _client(monkeypatch, _lp562_record())
    fake_document = SimpleNamespace(
        public_id="23a0b83c-b09a-4e89-b2c7-8251b7ac08e1",
        review_status="pending",
        accepted_extraction_id=None,
        norma_id=1,
        ReviewStatus=SimpleNamespace(PENDING="pending"),
    )

    def fake_stage(**kwargs):
        fake_document.norma_id = kwargs["norma"].pk
        return fake_document, True

    monkeypatch.setattr(
        "src.apps.ingestion.sapl_document_sync.stage_sapl_pdf_candidate", fake_stage
    )
    with override_settings(QA_ROOT=qa_root, NORMATIVE_ARCHIVE_ENABLED=True):
        result = staging.stage_sapl_normative_candidate(sapl_id=254, apply=True)

    norma = Norma.objects.get(sapl_id=254)
    assert result["mode"] == "applied"
    assert norma.tipo == "Lei Promulgada"
    assert norma.status == Norma.Status.PENDING
    assert norma.identity_json["series"] == "municipal_lp"
    assert norma.documento_base_id is None
    assert norma.texto_original == ""
    assert norma.texto_consolidado == ""
    assert "materia" not in norma.sapl_metadata
    assert result["text_accepted"] is False
    assert result["norma_linked_as_base"] is False
    assert result["matter_metadata_imported"] is False


@pytest.mark.django_db
def test_ordinary_1894_apply_stages_pending_without_inventing_publication_date(
    monkeypatch, tmp_path
):
    qa_root = tmp_path / "qa"
    _qa_env(monkeypatch, qa_root)
    _client(monkeypatch, _ordinary_1894_record())
    fake_document = SimpleNamespace(
        public_id="b5e5d2d8-9749-4a54-96a9-10dfb2b0aab0",
        review_status="pending",
        accepted_extraction_id=None,
        norma_id=1,
        ReviewStatus=SimpleNamespace(PENDING="pending"),
    )

    def fake_stage(**kwargs):
        fake_document.norma_id = kwargs["norma"].pk
        return fake_document, True

    monkeypatch.setattr(
        "src.apps.ingestion.sapl_document_sync.stage_sapl_pdf_candidate", fake_stage
    )
    with override_settings(QA_ROOT=qa_root, NORMATIVE_ARCHIVE_ENABLED=True):
        result = staging.stage_sapl_normative_candidate(sapl_id=3666, apply=True)

    norma = Norma.objects.get(sapl_id=3666)
    assert result["mode"] == "applied"
    assert norma.tipo == "Lei Ordinária"
    assert norma.data_norma.isoformat() == "1969-12-25"
    assert norma.data_publicacao is None
    assert norma.status == Norma.Status.PENDING
    assert norma.needs_review is True
    assert norma.documento_base_id is None
    assert norma.texto_original == ""
    assert norma.texto_consolidado == ""
    assert result["review_status"] == "pending"
    assert result["text_accepted"] is False
    assert result["norma_linked_as_base"] is False
