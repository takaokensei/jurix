from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

from src.apps.ingestion.management.commands.diagnose_qa_archive_overview import (
    _answer_shape_metrics,
    _validation_shape_metrics,
)

MODULE_PATH = Path(__file__).resolve().parents[2] / "scripts" / "normative_qa.py"
SPEC = importlib.util.spec_from_file_location("normative_qa_helper", MODULE_PATH)
qa = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(qa)


def test_accepts_only_dedicated_audit_targets():
    qa._validate_target(qa.DATABASE_URL, qa.REDIS_URL, qa.CACHE_REDIS_URL)


def test_qa_runner_allows_only_the_fixed_normative_api_benchmark_command():
    command = ["python", "scripts/benchmark_normative_api_qa.py"]
    assert qa._allowed_command(command) == [
        qa.sys.executable,
        "scripts/benchmark_normative_api_qa.py",
    ]
    with pytest.raises(ValueError):
        qa._allowed_command(command + ["--database", "production"])


def test_qa_runner_allows_only_one_bounded_sapl_incremental_page():
    command = [
        "python", "scripts/run_qa_sapl_incremental.py",
        "--tipo", "1", "--ano", "2026", "--limit", "10", "--max-pages", "1",
    ]
    assert qa._allowed_command(command) == [qa.sys.executable, *command[1:]]
    for changed in (
        command[:-1] + ["2"],
        command[:-3] + ["2025", "--limit", "10", "--max-pages", "1"],
        command[:-5] + ["100", "--max-pages", "20"],
        command + ["--full"],
    ):
        with pytest.raises(ValueError):
            qa._allowed_command(changed)
    repair = [
        "python", "scripts/run_qa_sapl_incremental.py",
        "--repair-checkpoint-page", "--tipo", "1", "--ano", "2026", "--limit", "10",
    ]
    assert qa._allowed_command(repair) == [qa.sys.executable, *repair[1:]]
    with pytest.raises(ValueError):
        qa._allowed_command(repair + ["--force"])

    metadata_only = [
        "python", "scripts/run_qa_sapl_incremental.py",
        "--tipo", "1", "--ano", "2026", "--limit", "10", "--max-pages", "4",
        "--metadata-only",
    ]
    assert qa._allowed_command(metadata_only) == [qa.sys.executable, *metadata_only[1:]]
    for unsafe in (
        metadata_only + ["--force"],
        [*metadata_only[:-1], "--max-pages", "5", "--metadata-only"],
        [*metadata_only[:-1], "--limit", "11", "--metadata-only"],
    ):
        with pytest.raises(ValueError):
            qa._allowed_command(unsafe)


def test_qa_runner_allows_only_read_only_relation_target_coverage_inspection():
    command = ["python", "manage.py", "inspect_archive_relation_target_coverage_qa"]
    assert qa._allowed_command(command) == [qa.sys.executable, *command[1:]]
    with pytest.raises(ValueError):
        qa._allowed_command(command + ["--apply"])


def test_qa_runner_limits_dom_sync_to_two_months_and_one_edition():
    base = ["python", "manage.py", "sync_dom_natal_editions_qa"]
    dry_run = base + ["--lookback-months", "1", "--max-new-total", "1"]
    apply = dry_run + ["--apply"]
    two_month_dry_run = base + ["--lookback-months", "2", "--max-new-total", "1"]
    two_month_apply = two_month_dry_run + ["--apply"]

    assert qa._allowed_command(dry_run) == [qa.sys.executable, *dry_run[1:]]
    assert qa._allowed_command(apply) == [qa.sys.executable, *apply[1:]]
    assert qa._allowed_command(two_month_dry_run) == [qa.sys.executable, *two_month_dry_run[1:]]
    assert qa._allowed_command(two_month_apply) == [qa.sys.executable, *two_month_apply[1:]]
    historical = base + [
        "--lookback-months", "1", "--max-new-total", "1", "--as-of", "2026-01-01"
    ]
    historical_apply = historical + ["--apply"]
    assert qa._allowed_command(historical) == [qa.sys.executable, *historical[1:]]
    assert qa._allowed_command(historical_apply) == [
        qa.sys.executable, *historical_apply[1:]
    ]
    today = date.today()
    for options in (
        ["--lookback-months", "3", "--max-new-total", "1"],
        ["--lookback-months", "4", "--max-new-total", "1", "--apply"],
        ["--lookback-months", "1", "--max-new-total", "2"],
        ["--lookback-months", "2", "--max-new-total", "2"],
        ["--lookback-months", "1", "--max-new-total", "1", "--force"],
        ["--lookback-months", "1", "--max-new-total", "1", "--as-of", "2026-01-1"],
        ["--lookback-months", "1", "--max-new-total", "1", "--as-of", (today + timedelta(days=1)).isoformat()],
        ["--lookback-months", "1", "--max-new-total", "1", "--as-of", (today - timedelta(days=367)).isoformat()],
    ):
        with pytest.raises(ValueError):
            qa._allowed_command(base + options)


def test_qa_runner_allows_only_one_bounded_dom_blob_repair():
    base = ["python", "manage.py", "repair_dom_edition_blob_qa"]
    target = ["--year", str(date.today().year - 1), "--month", "12", "--edition-number", "5922"]
    assert qa._allowed_command(base + target) == [qa.sys.executable, *base[1:], *target]
    assert qa._allowed_command(base + target + ["--apply"]) == [
        qa.sys.executable, *base[1:], *target, "--apply"
    ]
    for options in (
        target + ["--force"],
        ["--year", "2020", "--month", "12", "--edition-number", "5922"],
        ["--year", str(date.today().year - 1), "--month", "13", "--edition-number", "5922"],
        ["--year", str(date.today().year - 1), "--month", "12", "--edition-number", "0"],
    ):
        with pytest.raises(ValueError):
            qa._allowed_command(base + options)


def test_qa_runner_limits_archive_retrieval_inspection_to_the_authorized_case():
    command = [
        "python", "manage.py", "inspect_archive_candidate_retrieval_qa",
        "--document-id", "eaa13513-6cfc-4edf-8027-c6a7cc6d70b7",
        "--question", "O que dispõe o Art. 262 da Lei Complementar nº 258/2024?",
    ]
    assert qa._allowed_command(command) == [qa.sys.executable, *command[1:]]
    with pytest.raises(ValueError, match="restricted to the authorized"):
        qa._allowed_command(command[:-1] + ["O que dispõe o Art. 1º de outra lei?"])

    two_articles = command[:-1] + [
        "Resuma a relação entre o Art. 262 (regra transitória) e o Art. 266 (vigência) da Lei Complementar nº 258/2024. Cite os dois dispositivos separadamente e não calcule a data em calendário."
    ]
    assert qa._allowed_command(two_articles) == [qa.sys.executable, *two_articles[1:]]

    accessibility_query = command[:-1] + [
        "Quais exigências de acessibilidade para edificações aparecem no Código de Obras de Natal? Resuma apenas o que os dispositivos recuperados dizem, cite cada artigo e explique o que ainda não se pode concluir sobre uma obra específica."
    ]
    assert qa._allowed_command(accessibility_query) == [
        qa.sys.executable, *accessibility_query[1:]
    ]
    with pytest.raises(ValueError, match="restricted to the authorized"):
        qa._allowed_command(accessibility_query[:-1] + [
            "Inspecione qualquer texto arbitrário do acervo inteiro."
        ])

    contextual_followup = command[:-1] + [
        "E qual artigo define a data de entrada em vigor? (contexto normativo: Lei Complementar nº 258/2024)"
    ]
    assert qa._allowed_command(contextual_followup) == [qa.sys.executable, *contextual_followup[1:]]

    effective_date_followup = command[:-1] + [
        "E quando a lei passou a vigorar? (contexto normativo: Lei Complementar nº 258/2024)"
    ]
    assert qa._allowed_command(effective_date_followup) == [
        qa.sys.executable, *effective_date_followup[1:]
    ]

    lc271_article_20 = [
        "python", "manage.py", "inspect_archive_candidate_retrieval_qa",
        "--document-id", "cb810b42-ecea-4cbc-870a-b2581c30df6c",
        "--question", "O que prevê o Art. 1º da Lei Complementar nº 271/2025?",
    ]
    assert qa._allowed_command(lc271_article_20) == [
        qa.sys.executable, *lc271_article_20[1:]
    ]
    lc271_vs_ctm_2024 = [
        "python", "manage.py", "inspect_archive_candidate_retrieval_qa",
        "--document-id", "cb810b42-ecea-4cbc-870a-b2581c30df6c",
        "--question",
        "Compare o texto do Art. 20 da Lei nº 3.882/1989 na consolidação municipal de 2024 com a redação substitutiva transcrita no Art. 1º da LC nº 271/2025. Mostre apenas as fontes e diferenças textuais, sem concluir vigência atual.",
    ]
    assert qa._allowed_command(lc271_vs_ctm_2024) == [
        qa.sys.executable, *lc271_vs_ctm_2024[1:]
    ]
    assert qa._allowed_command(lc271_vs_ctm_2024 + ["--generate"]) == [
        qa.sys.executable, *lc271_vs_ctm_2024[1:], "--generate"
    ]
    with pytest.raises(ValueError, match="exact questions"):
        qa._allowed_command(
            lc271_vs_ctm_2024[:-1]
            + ["Pergunta arbitrária sobre uma peça processual.", "--generate"]
        )

    lc120_art18 = [
        "python", "manage.py", "inspect_archive_candidate_retrieval_qa",
        "--document-id", "f4a5c8f6-7ca2-4b5c-935e-033572a33510",
        "--question",
        "A Lei Complementar Municipal nº 120/2010, Art. 18, foi alterada ou revogada? Compare a redação original e a atual, diga o que o acervo permite afirmar e cite as fontes.",
    ]
    assert qa._allowed_command(lc120_art18) == [
        qa.sys.executable, *lc120_art18[1:]
    ]
    with pytest.raises(ValueError, match="restricted to the authorized public QA candidates"):
        qa._allowed_command(lc120_art18[:-1] + ["Pergunta arbitrária sobre qualquer documento."])

    pgm_currentness_check = command[:-1] + [
        "Para um processo de licenciamento municipal, posso citar o Art. 59 da Lei Complementar nº 258/2024 como redação atual? Verifique se houve alteração posterior do dispositivo e diferencie lei aprovada de proposição em tramitação."
    ]
    assert qa._allowed_command(pgm_currentness_check) == [
        qa.sys.executable, *pgm_currentness_check[1:]
    ]

    pgm_transition_case = [
        "python", "manage.py", "inspect_archive_candidate_retrieval_qa",
        "--document-id", "6b025442-7977-4f27-96f2-2318d2c714be",
        "--question",
        "Em um processo protocolado antes da entrada em vigor da LC 258/2024 e ainda sem despacho decisório, como devo verificar se a regra do Art. 21 da LC 55/2004 ainda pode ser aplicada? Considere também o Art. 260, IV, e o Art. 262 da LC 258/2024. Separe o que os PDFs comprovam do que permanece inconclusivo.",
    ]
    assert qa._allowed_command(pgm_transition_case + ["--generate"]) == [
        qa.sys.executable, *pgm_transition_case[1:], "--generate"
    ]
    with pytest.raises(ValueError, match="exact public PGM QA scenario"):
        qa._allowed_command(command + ["--generate"])

    lp275_revocation_question = [
        "python", "manage.py", "inspect_archive_candidate_retrieval_qa",
        "--document-id", "c452bfe5-1138-4962-a3f2-c4cc9b662007",
        "--question",
        "A Lei Complementar nº 258/2024, Art. 260, inciso V, revoga expressamente o Art. 21 da Lei Promulgada nº 275/2009? O que os documentos disponíveis permitem afirmar e o que permanece pendente de confirmação jurídica?",
    ]
    assert qa._allowed_command(lp275_revocation_question) == [
        qa.sys.executable, *lp275_revocation_question[1:]
    ]
    with pytest.raises(ValueError, match="restricted to the authorized"):
        qa._allowed_command(lp275_revocation_question[:-1] + [
            "Pergunta não autorizada sobre outro documento."
        ])
    assert qa._allowed_command(lp275_revocation_question + ["--generate"]) == [
        qa.sys.executable, *lp275_revocation_question[1:], "--generate"
    ]


def test_qa_runner_limits_sapl_candidate_extraction_to_promulgated_candidates():
    command = [
        "python", "manage.py", "extract_sapl_normative_candidate_qa",
        "--document-id", "00c841d2-4b08-42a3-80b1-f018b1e86d43",
        "--max-pages", "200", "--max-ocr-pages", "0",
    ]
    assert qa._allowed_command(command) == [qa.sys.executable, *command[1:]]
    new_public_law_candidate = command.copy()
    new_public_law_candidate[4] = "a2334a00-772f-4b38-9153-c88ba13ebe5b"
    assert qa._allowed_command(new_public_law_candidate) == [
        qa.sys.executable,
        *new_public_law_candidate[1:],
    ]
    lc198_candidate = command.copy()
    lc198_candidate[4] = "fe950bad-c738-4404-822b-2214f802f236"
    assert qa._allowed_command(lc198_candidate) == [
        qa.sys.executable,
        *lc198_candidate[1:],
    ]
    newly_staged_ordinary_law = command.copy()
    newly_staged_ordinary_law[4] = "f08cb4c6-41e8-4332-8c4f-2a764ca2f6a6"
    assert qa._allowed_command(newly_staged_ordinary_law) == [
        qa.sys.executable,
        *newly_staged_ordinary_law[1:],
    ]
    newly_staged_4885 = command.copy()
    newly_staged_4885[4] = "4f246b2d-6c49-4c70-9014-5c255f969242"
    assert qa._allowed_command(newly_staged_4885) == [
        qa.sys.executable,
        *newly_staged_4885[1:],
    ]
    with pytest.raises(ValueError, match="promulgated QA allowlist"):
        qa._allowed_command(command[:4] + ["f4a5c8f6-7ca2-4b5c-935e-033572a33510"] + command[5:])


def test_qa_runner_allows_only_no_argument_lc261_unlinked_extraction():
    base = ["python", "manage.py", "extract_lc261_unlinked_candidate_qa"]
    assert qa._allowed_command(base) == [qa.sys.executable, *base[1:]]
    for unsafe in (base + ["--apply"], base + ["--document-id", "anything"]):
        with pytest.raises(ValueError, match="accepts no arguments"):
            qa._allowed_command(unsafe)


def test_qa_runner_limits_relation_candidate_extraction_to_exact_qa_chain_ids():
    base = ["python", "manage.py", "extract_lc_chain_relation_candidates_qa"]
    dry_run = base + ["--extraction-id", "7135"]
    apply = dry_run + ["--apply"]
    both = base + ["--extraction-id", "7135", "--extraction-id", "7141"]
    article_dry_run = base + ["--extraction-id", "7135", "--source-article", "118"]
    article_apply = article_dry_run + ["--apply"]

    assert qa._allowed_command(dry_run) == [qa.sys.executable, *dry_run[1:]]
    assert qa._allowed_command(apply) == [qa.sys.executable, *apply[1:]]
    assert qa._allowed_command(both) == [qa.sys.executable, *both[1:]]
    assert qa._allowed_command(article_dry_run) == [qa.sys.executable, *article_dry_run[1:]]
    assert qa._allowed_command(article_apply) == [qa.sys.executable, *article_apply[1:]]
    lc198_reference_preview = base + ["--extraction-id", "7144"]
    assert qa._allowed_command(lc198_reference_preview) == [
        qa.sys.executable, *lc198_reference_preview[1:]
    ]
    lc271_ocr_revision = base + ["--extraction-id", "7150", "--source-article", "5"]
    assert qa._allowed_command(lc271_ocr_revision) == [
        qa.sys.executable, *lc271_ocr_revision[1:]
    ]
    lc271_later_amendments = base + ["--extraction-id", "7149", "--source-article", "3"]
    assert qa._allowed_command(lc271_later_amendments) == [
        qa.sys.executable, *lc271_later_amendments[1:]
    ]
    lc271_native_revision = base + ["--extraction-id", "7151", "--source-article", "5"]
    assert qa._allowed_command(lc271_native_revision) == [
        qa.sys.executable, *lc271_native_revision[1:]
    ]
    current_qa_lc271 = base + ["--extraction-id", "6920", "--source-article", "1"]
    assert qa._allowed_command(current_qa_lc271) == [
        qa.sys.executable, *current_qa_lc271[1:]
    ]
    lc258_article_261 = base + ["--extraction-id", "7141", "--source-article", "261"]
    assert qa._allowed_command(lc258_article_261) == [
        qa.sys.executable, *lc258_article_261[1:]
    ]
    lc258_repeal_article = base + ["--extraction-id", "1391", "--source-article", "260"]
    assert qa._allowed_command(lc258_repeal_article) == [
        qa.sys.executable, *lc258_repeal_article[1:]
    ]
    for unsafe in (
        base + ["--extraction-id", "1"],
        base + ["--extraction-id", "7135", "--extraction-id", "7135"],
        base + ["--extraction-id", "7135", "--apply", "--extraction-id", "7141"],
        base + ["--extraction-id", "7135", "--dry-run"],
        base + ["--extraction-id", "7135", "--apply", "--force"],
        base + ["--extraction-id", "7141", "--source-article", "118"],
        base + ["--extraction-id", "7141", "--source-article", "260"],
        base + ["--extraction-id", "1391", "--source-article", "261"],
        base + ["--extraction-id", "7135", "--source-article", "117"],
        base + ["--extraction-id", "7135", "--source-article", "118", "--source-article", "118"],
        base + ["--extraction-id", "7135", "--source-article"],
    ):
        with pytest.raises(ValueError):
            qa._allowed_command(unsafe)


def test_qa_runner_allows_only_bounded_resumable_archive_relation_candidates():
    base = ["python", "manage.py", "extract_archive_relation_candidates_qa"]
    dry_run = base + ["--dry-run", "--batch-size", "10"]
    first_batch = base + ["--apply", "--batch-size", "10", "--max-batches", "10"]
    resume = base + ["--apply", "--batch-size", "10", "--max-batches", "10", "--resume"]

    assert qa._allowed_command(dry_run) == [qa.sys.executable, *dry_run[1:]]
    assert qa._allowed_command(first_batch) == [qa.sys.executable, *first_batch[1:]]
    assert qa._allowed_command(resume) == [qa.sys.executable, *resume[1:]]
    for unsafe in (
        base + ["--apply", "--dry-run"],
        base + ["--apply", "--batch-size", "11"],
        base + ["--apply", "--batch-size", "0"],
        base + ["--apply", "--max-batches", "11"],
        base + ["--dry-run", "--resume", "--resume"],
        base + ["--apply", "--force"],
    ):
        with pytest.raises(ValueError):
            qa._allowed_command(unsafe)


def test_qa_runner_confines_lc55_candidate_staging_to_its_qa_evidence_file(tmp_path, monkeypatch):
    qa_root = tmp_path / "qa"
    pdf = qa_root / "evidence" / "lc55-2004" / "lc55-codigo-obras-consolidado-julho-2019.pdf"
    pdf.parent.mkdir(parents=True)
    pdf.write_bytes(b"%PDF-test")
    monkeypatch.setenv("JURIX_QA_ROOT", str(qa_root))
    base = [
        "python", "manage.py", "stage_lc55_official_candidate_qa",
        "--pdf-path", str(pdf),
    ]

    assert qa._allowed_command(base) == [qa.sys.executable, *base[1:]]
    assert qa._allowed_command(base + ["--apply"]) == [qa.sys.executable, *base[1:], "--apply"]
    with pytest.raises(ValueError, match="exact QA evidence directory"):
        qa._allowed_command(base[:-1] + [str(tmp_path / "outside.pdf")])


def test_qa_runner_allows_only_the_fixed_container_qa_lc55_original():
    base = [
        "python", "manage.py", "stage_lc55_original_candidate_qa",
        "--pdf-path", "/app/data/normative-qa/evidence/lc55-2004/lc55-original-2004.pdf",
    ]
    assert qa._allowed_command(base) == [qa.sys.executable, *base[1:]]
    assert qa._allowed_command(base + ["--apply"]) == [qa.sys.executable, *base[1:], "--apply"]
    for unsafe in (
        base[:-1] + ["/tmp/other.pdf"],
        base + ["--force"],
    ):
        with pytest.raises(ValueError, match="fixed QA evidence PDF"):
            qa._allowed_command(unsafe)


def test_qa_runner_allows_only_bounded_lc208_unlinked_candidate_staging():
    base = ["python", "manage.py", "stage_lc208_unlinked_sapl_candidate_qa"]
    assert qa._allowed_command(base) == [qa.sys.executable, *base[1:]]
    assert qa._allowed_command(base + ["--apply"]) == [qa.sys.executable, *base[1:], "--apply"]
    for unsafe in (base + ["--force"], base + ["--sapl-id", "4052"]):
        with pytest.raises(ValueError, match="only optional --apply"):
            qa._allowed_command(unsafe)


def test_qa_runner_allows_only_bounded_lc261_unlinked_candidate_staging():
    base = ["python", "manage.py", "stage_lc261_unlinked_sapl_candidate_qa"]
    assert qa._allowed_command(base) == [qa.sys.executable, *base[1:]]
    assert qa._allowed_command(base + ["--apply"]) == [qa.sys.executable, *base[1:], "--apply"]
    for unsafe in (base + ["--force"], base + ["--sapl-id", "1160"]):
        with pytest.raises(ValueError, match="only optional --apply"):
            qa._allowed_command(unsafe)
    with pytest.raises(ValueError, match="only optional --apply"):
        qa._allowed_command(base + ["--source-url", "https://attacker.invalid/file.pdf"])


def test_qa_runner_confines_bvn_4566_staging_to_exact_qa_evidence_file(tmp_path, monkeypatch):
    qa_root = tmp_path / "qa"
    pdf = qa_root / "evidence" / "lc258-4566-1992" / "lei_4.566.pdf"
    pdf.parent.mkdir(parents=True)
    pdf.write_bytes(b"%PDF-test")
    monkeypatch.setenv("JURIX_QA_ROOT", str(qa_root))
    base = [
        "python", "manage.py", "stage_bvn_4566_1992_candidate_qa",
        "--pdf-path", str(pdf),
    ]

    assert qa._allowed_command(base) == [qa.sys.executable, *base[1:]]
    assert qa._allowed_command(base + ["--apply"]) == [qa.sys.executable, *base[1:], "--apply"]
    with pytest.raises(ValueError, match="exact QA evidence directory"):
        qa._allowed_command(base[:-1] + [str(tmp_path / "outside.pdf")])
    with pytest.raises(ValueError, match="only --pdf-path and --apply"):
        qa._allowed_command(base + ["--source-url", "https://attacker.invalid/file.pdf"])


def test_qa_runner_confines_lp275_staging_to_exact_qa_evidence_file(tmp_path, monkeypatch):
    qa_root = tmp_path / "qa"
    pdf = qa_root / "evidence" / "lp275-2009" / "lei-promulgada-0275-2009-oficial.pdf"
    pdf.parent.mkdir(parents=True)
    pdf.write_bytes(b"%PDF-test")
    monkeypatch.setenv("JURIX_QA_ROOT", str(qa_root))
    base = [
        "python", "manage.py", "stage_lp275_2009_candidate_qa",
        "--pdf-path", str(pdf),
    ]

    assert qa._allowed_command(base) == [qa.sys.executable, *base[1:]]
    assert qa._allowed_command(base + ["--apply"]) == [qa.sys.executable, *base[1:], "--apply"]
    with pytest.raises(ValueError, match="exact QA evidence directory"):
        qa._allowed_command(base[:-1] + [str(tmp_path / "outside.pdf")])
    with pytest.raises(ValueError, match="only --pdf-path and --apply"):
        qa._allowed_command(base + ["--source-url", "https://attacker.invalid/file.pdf"])


def test_qa_runner_confines_archive_overview_diagnostic_to_qa_output(tmp_path, monkeypatch):
    qa_root = tmp_path / "qa"
    qa_root.mkdir()
    monkeypatch.setenv("JURIX_QA_ROOT", str(qa_root))
    output = str(qa_root / "overview-metrics.json")
    command = ["python", "manage.py", "diagnose_qa_archive_overview", "--output", output]

    assert qa._allowed_command(command) == [qa.sys.executable, *command[1:]]
    with pytest.raises(ValueError, match="output must stay"):
        qa._allowed_command(
            ["python", "manage.py", "diagnose_qa_archive_overview", "--output", str(tmp_path / "outside.json")]
        )
    with pytest.raises(ValueError, match="exactly one"):
        qa._allowed_command(command + ["--model", "other"])


def test_archive_diagnostic_records_only_grounding_shape_not_claim_text():
    metrics = _validation_shape_metrics(
        {
            "grounded": False,
            "source_only": True,
            "grounding": {
                "score": 0.5,
                "claims": [
                    {
                        "claim": "segredo jurídico [[1]]",
                        "supported": False,
                        "evidence": [],
                        "rejected_matches": [
                            {
                                "lexical_overlap": 0.4,
                                "lexical_ok": False,
                                "numeric_ok": True,
                                "negation_ok": True,
                                "citation_ok": True,
                                "certainty_ok": True,
                            }
                        ],
                    },
                    {
                        "claim": "outra afirmação [[2]]",
                        "supported": False,
                        "evidence": [],
                        "rejected_matches": [
                            {
                                "lexical_overlap": 0.8,
                                "lexical_ok": True,
                                "numeric_ok": False,
                                "negation_ok": True,
                                "citation_ok": True,
                                "certainty_ok": True,
                            }
                        ],
                    },
                    {"claim": "claim sem citação", "supported": False, "evidence": []},
                    {"claim": "afirmação aceita [[1]]", "supported": True, "evidence": [{"id": 1}]},
                ],
                "failed_claims": ["segredo jurídico", "outra afirmação", "claim sem citação"],
            },
        },
        sources=[
            {
                "citation_index": 1,
                "evidence_text": "texto do excerto selecionado",
                "dispositivo_ref": "Art. 1º",
            },
            {"citation_index": 2, "evidence_text": ""},
        ],
        answer="O Art. 1º apresenta a afirmação teste. [[1]]",
    )

    assert metrics["failed_claim_count"] == 3
    assert metrics["failed_claim_records"] == 3
    assert metrics["failed_records_without_evidence"] == 3
    assert metrics["failed_records_with_evidence"] == 0
    assert metrics["failed_records_without_citation_marker"] == 1
    assert metrics["failed_records_citing_unsampled_evidence"] == 1
    assert metrics["failed_records_citing_sampled_evidence_without_match"] == 1
    assert metrics["closest_rejection_failures"] == {
        "lexical": 1,
        "numeric": 1,
        "negation": 0,
        "citation": 0,
        "certainty": 0,
        "no_candidate": 1,
    }
    assert metrics["candidate_answer_shape"]["distinct_citation_marker_count"] == 1
    assert metrics["candidate_answer_shape"]["repeated_citation_marker_count"] == 0
    assert metrics["candidate_answer_shape"]["meets_partial_overview_breadth"] is True
    assert metrics["candidate_answer_shape"]["meets_partial_overview_source_alignment"] is True
    assert metrics["candidate_answer_shape"]["has_redundant_content_phrase"] is False
    assert "failure_shapes" not in metrics
    assert "segredo jurídico" not in str(metrics)
    assert "afirmação teste" not in str(metrics)


def test_archive_diagnostic_reports_article_citation_misalignment_without_text():
    metrics = _validation_shape_metrics(
        {"grounded": True, "source_only": True, "grounding": {"claims": [], "failed_claims": []}},
        sources=[{"citation_index": 1, "evidence_text": "conteúdo", "dispositivo_ref": "Art. 2º"}],
        answer="O Art. 1º apresenta a afirmação teste. [[1]]",
    )

    assert metrics["candidate_answer_shape"]["meets_partial_overview_breadth"] is True
    assert metrics["candidate_answer_shape"]["meets_partial_overview_source_alignment"] is False
    assert "afirmação teste" not in str(metrics)


def test_archive_diagnostic_records_answer_shape_without_answer_text():
    metrics = _answer_shape_metrics(
        "Síntese sobre o tema. [[1]]\n\nA amostra consultada cobre 30 de 39 artigos."
    )

    assert metrics["citation_marker_count"] == 1
    assert metrics["heading_count"] == 0
    assert metrics["paragraph_count"] == 2
    assert metrics["has_partial_coverage_note"] is True
    assert metrics["has_generic_partial_notice"] is False
    assert "Síntese sobre o tema" not in str(metrics)


def test_qa_runner_confines_live_rag_experiment_to_versioned_cases_and_qa_output(
    tmp_path, monkeypatch
):
    qa_root = tmp_path / "qa"
    qa_root.mkdir()
    monkeypatch.setenv("JURIX_QA_ROOT", str(qa_root))
    cases = "benchmarks/corpus/municipal_natal/rag-experiment-smoke.v1.jsonl"
    output = str(qa_root / "rag-smoke.jsonl")
    command = [
        "python", "scripts/collect_normative_rag_experiment.py",
        "--cases", cases, "--output", output,
    ]

    assert qa._allowed_command(command) == [qa.sys.executable, *command[1:]]
    project_gold_command = [
        "python", "scripts/collect_normative_rag_experiment.py",
        "--project-gold", "benchmarks/corpus/municipal_natal/project-gold.v1.json",
        "--output", output, "--max-cases", "28", "--no-warm-cache",
    ]
    assert qa._allowed_command(project_gold_command) == [
        qa.sys.executable, *project_gold_command[1:]
    ]
    with pytest.raises(ValueError, match="exactly one explicit reference"):
        qa._allowed_command(project_gold_command + ["--cases", cases])
    with pytest.raises(ValueError, match="reference must be inside"):
        qa._allowed_command([
            "python", "scripts/collect_normative_rag_experiment.py",
            "--project-gold", str(tmp_path / "external-gold.json"),
            "--output", output,
        ])
    with pytest.raises(ValueError, match="output must stay"):
        qa._allowed_command(command[:-1] + [str(tmp_path / "outside.jsonl")])
    with pytest.raises(ValueError, match="reference must be inside"):
        qa._allowed_command([
            "python", "scripts/collect_normative_rag_experiment.py",
            "--cases", str(tmp_path / "external.jsonl"), "--output", output,
        ])


def test_qa_runner_allows_collector_help_without_relaxing_experiment_paths():
    command = ["python", "scripts/collect_normative_rag_experiment.py", "--help"]

    assert qa._allowed_command(command) == [qa.sys.executable, *command[1:]]
    with pytest.raises(ValueError, match="exactly one explicit reference and output"):
        qa._allowed_command([
            "python", "scripts/collect_normative_rag_experiment.py", "--no-warm-cache",
        ])


def test_qa_runner_confines_project_gold_archive_retrieval_evaluation(tmp_path, monkeypatch):
    qa_root = tmp_path / "qa"
    qa_root.mkdir()
    monkeypatch.setenv("JURIX_QA_ROOT", str(qa_root))
    output = str(qa_root / "archive-retrieval.json")
    command = [
        "python", "scripts/evaluate_pgm_project_gold_archive.py",
        "--output", output,
    ]

    assert qa._allowed_command(command) == [qa.sys.executable, *command[1:]]
    with pytest.raises(ValueError, match="only the adopted project gold"):
        qa._allowed_command([
            "python", "scripts/evaluate_pgm_project_gold_archive.py",
            "--gold", str(tmp_path / "other-gold.json"), "--output", output,
        ])
    with pytest.raises(ValueError, match="output must stay"):
        qa._allowed_command([
            "python", "scripts/evaluate_pgm_project_gold_archive.py",
            "--output", str(tmp_path / "outside.json"),
        ])
    with pytest.raises(ValueError, match="between 1 and 48"):
        qa._allowed_command([*command, "--limit", "49"])


def test_qa_runner_allows_only_the_live_rag_browser_smoke():
    command = ["node", "tests/js/normative-rag-live-smoke.mjs"]
    assert qa._allowed_command(command) == ["node.exe", *command[1:]]
    with pytest.raises(ValueError):
        qa._allowed_command(command + ["https://example.com"])

    pgm_command = ["node", "tests/js/pgm-workflow-smoke.mjs"]
    assert qa._allowed_command(pgm_command) == ["node.exe", *pgm_command[1:]]
    with pytest.raises(ValueError):
        qa._allowed_command(pgm_command + ["https://example.com"])

    related_matter_command = ["node", "tests/js/pgm-sapl-related-matter-smoke.mjs"]
    assert qa._allowed_command(related_matter_command) == [
        "node.exe", *related_matter_command[1:]
    ]
    with pytest.raises(ValueError):
        qa._allowed_command(related_matter_command + ["https://example.com"])

    currentness_command = ["node", "tests/js/pgm-article-currentness-smoke.mjs"]
    assert qa._allowed_command(currentness_command) == ["node.exe", *currentness_command[1:]]
    with pytest.raises(ValueError):
        qa._allowed_command(currentness_command + ["https://example.com"])

    foundation_command = ["node", "tests/js/foundation-check.browser.smoke.mjs"]
    assert qa._allowed_command(foundation_command) == ["node.exe", *foundation_command[1:]]
    with pytest.raises(ValueError):
        qa._allowed_command(foundation_command + ["https://example.com"])


@pytest.mark.parametrize(
    "database,redis,cache",
    [
        ("sqlite:///db.sqlite3", qa.REDIS_URL, qa.CACHE_REDIS_URL),
        ("postgresql://user:secret@db:5432/jurix", qa.REDIS_URL, qa.CACHE_REDIS_URL),
        (qa.DATABASE_URL, "redis://localhost:6379/0", qa.CACHE_REDIS_URL),
        (qa.DATABASE_URL, qa.REDIS_URL, "redis://remote:6379/1"),
    ],
)
def test_rejects_non_qa_targets(database, redis, cache):
    with pytest.raises(ValueError):
        qa._validate_target(database, redis, cache)


def test_command_runner_does_not_accept_shell_or_unknown_commands():
    with pytest.raises(ValueError):
        qa._allowed_command(["python", "-c", "print('not allowed')"])
    with pytest.raises(ValueError):
        qa._allowed_command(["python", "manage.py", "flush"])


def test_command_runner_maps_python_to_active_interpreter():
    assert qa._allowed_command(["python", "manage.py", "check"])[0] == qa.sys.executable


def test_read_only_source_health_command_is_allowlisted_without_extra_arguments():
    command = ["python", "manage.py", "check_source_sync_health"]
    assert qa._allowed_command(command) == [qa.sys.executable, *command[1:]]
    dom_command = command + ["--source", "dom_natal", "--max-age-hours", "72"]
    assert qa._allowed_command(dom_command) == [qa.sys.executable, *dom_command[1:]]
    details_command = command + ["--source", "sapl", "--max-age-hours", "8760", "--details"]
    assert qa._allowed_command(details_command) == [qa.sys.executable, *details_command[1:]]
    with pytest.raises(ValueError, match="not on the QA allowlist"):
        qa._allowed_command(command + ["--source", "other"])
    with pytest.raises(ValueError, match="QA limit"):
        qa._allowed_command(command + ["--max-age-hours", "8761"])
    with pytest.raises(ValueError, match="require values"):
        qa._allowed_command(command + ["--source"])
    with pytest.raises(ValueError, match="not on the QA allowlist"):
        qa._allowed_command(command + ["--details", "--raw-error"])
    with pytest.raises(ValueError, match="duplicated"):
        qa._allowed_command(command + ["--details", "--details"])


def test_target_reconciliation_allows_only_bounded_read_only_diagnostics():
    command = [
        "python", "manage.py", "reconcile_targets", "--dry-run", "--limit", "50000"
    ]
    assert qa._allowed_command(command) == [qa.sys.executable, *command[1:]]
    detailed = command + ["--details"]
    assert qa._allowed_command(detailed) == [qa.sys.executable, *detailed[1:]]
    for unsafe in (
        ["python", "manage.py", "reconcile_targets", "--limit", "50000"],
        command + ["--apply"],
        detailed + ["--raw-text"],
        ["python", "manage.py", "reconcile_targets", "--dry-run", "--limit", "50001"],
    ):
        with pytest.raises(ValueError):
            qa._allowed_command(unsafe)


def test_dom_gazette_boundary_inspection_requires_one_bounded_explicit_edition():
    command = [
        "python", "manage.py", "inspect_dom_gazette_boundaries_qa",
        "--year", "2026", "--month", "10", "--edition-number", "6213",
        "--kind", "regular", "--max-pages", "200",
    ]
    assert qa._allowed_command(command) == [qa.sys.executable, *command[1:]]
    for unsafe in (
        command + ["--apply"],
        command[:-2] + ["--kind", "any"],
        command[:-4] + ["--edition-number", "999999999", "--kind", "regular"],
        command[:-4],
        command + ["--max-pages", "501"],
    ):
        with pytest.raises(ValueError):
            qa._allowed_command(unsafe)


def test_sapl_diagnostic_is_exact_bounded_read_only_probe_to_natal():
    command = [
        "python", "manage.py", "diagnose_sapl", "--limit", "10", "--max-pages", "4",
    ]
    assert qa._allowed_command(command) == [qa.sys.executable, *command[1:]]
    for unsafe in (
        command[:-1] + ["50"],
        command + ["--apply"],
        command[:2] + ["ingest_sapl"],
    ):
        with pytest.raises(ValueError):
            qa._allowed_command(unsafe)

    scoped = qa._command_environment(
        {"JURIX_QA_ONLY": "1", "SAPL_BASE_URL": "http://untrusted.invalid/api"},
        command,
    )
    assert scoped["SAPL_BASE_URL"] == "https://sapl.natal.rn.leg.br/api"


def test_archive_sapl_crosswalk_is_limited_to_read_only_page_budgets():
    prefix = ["python", "manage.py", "audit_archive_sapl_crosswalk_qa"]
    for command in (
        prefix + ["--max-pages", "2", "--page-size", "100"],
        prefix + ["--max-pages", "100", "--page-size", "100"],
    ):
        assert qa._allowed_command(command) == [qa.sys.executable, *command[1:]]
        scoped = qa._command_environment(
            {"JURIX_QA_ONLY": "1", "SAPL_BASE_URL": "http://untrusted.invalid/api"},
            command,
        )
        assert scoped["SAPL_BASE_URL"] == "https://sapl.natal.rn.leg.br/api"

    for unsafe in (
        prefix + ["--max-pages", "101", "--page-size", "100"],
        prefix + ["--max-pages", "2", "--page-size", "101"],
        prefix + ["--max-pages", "2", "--page-size", "100", "--apply"],
        prefix + ["--max-pages", "100", "--page-size", "50"],
    ):
        with pytest.raises(ValueError):
            qa._allowed_command(unsafe)


def test_temporary_reviewer_credential_is_scoped_to_synthetic_seed(monkeypatch):
    secret = "qa-reviewer-secret-never-print-this"
    monkeypatch.setenv("JURIX_QA_REVIEWER_PASSWORD", secret)
    base = {"JURIX_QA_ONLY": "1"}
    seed_env = qa._command_environment(base, ["python", "manage.py", "seed_normative_qa", "--output", "qa.json"])
    review_env = qa._command_environment(base, ["node", "tests/js/normative-admin-review.browser.test.mjs"])
    collections_env = qa._command_environment(
        base, ["node", "tests/js/normative-collections.browser.test.mjs"]
    )
    check_env = qa._command_environment(base, ["python", "manage.py", "check"])
    assert seed_env["JURIX_QA_REVIEWER_PASSWORD"] == secret
    assert review_env["JURIX_QA_REVIEWER_PASSWORD"] == secret
    assert collections_env["JURIX_QA_REVIEWER_PASSWORD"] == secret
    assert "JURIX_QA_REVIEWER_PASSWORD" not in check_env


def test_qa_runner_scopes_reviewer_provisioning_to_exact_create_and_disable_commands(monkeypatch):
    secret = "qa-reviewer-secret-never-print-this"
    username = "jurix-pgm-preview-a1b2c3d4"
    monkeypatch.setenv("JURIX_QA_REVIEWER_PASSWORD", secret)
    monkeypatch.setenv("JURIX_QA_REVIEWER_USERNAME", username)
    create = ["python", "manage.py", "provision_pgm_qa_reviewer"]
    disable = ["python", "manage.py", "provision_pgm_qa_reviewer", "--disable"]
    preview_create = [
        "python", "manage.py", "provision_pgm_qa_reviewer", "--username", username,
    ]
    pending_relations_create = [
        *preview_create, "--include-pending-relations",
    ]
    preview_disable = [*preview_create, "--disable"]

    assert qa._allowed_command(create) == [qa.sys.executable, *create[1:]]
    assert qa._allowed_command(disable) == [qa.sys.executable, *disable[1:]]
    assert qa._allowed_command(preview_create) == [qa.sys.executable, *preview_create[1:]]
    assert qa._allowed_command(pending_relations_create) == [
        qa.sys.executable, *pending_relations_create[1:],
    ]
    assert qa._allowed_command(preview_disable) == [qa.sys.executable, *preview_disable[1:]]
    for unsafe in (
        create + ["--username", "other"],
        ["python", "manage.py", "provision_pgm_qa_reviewer", "--username", "other"],
        pending_relations_create + ["--force"],
        disable + ["--force"],
    ):
        with pytest.raises(ValueError):
            qa._allowed_command(unsafe)

    create_env = qa._command_environment({"JURIX_QA_ONLY": "1"}, create)
    disable_env = qa._command_environment({"JURIX_QA_ONLY": "1"}, disable)
    preview_create_env = qa._command_environment({"JURIX_QA_ONLY": "1"}, preview_create)
    check_env = qa._command_environment({"JURIX_QA_ONLY": "1"}, ["python", "manage.py", "check"])
    assert create_env["JURIX_QA_REVIEWER_PASSWORD"] == secret
    assert preview_create_env["JURIX_QA_REVIEWER_PASSWORD"] == secret
    assert "JURIX_QA_REVIEWER_PASSWORD" not in disable_env
    assert "JURIX_QA_REVIEWER_PASSWORD" not in check_env
    assert "JURIX_QA_REVIEWER_USERNAME" not in check_env


def test_qa_runner_scopes_candidate_review_browser_credentials_to_local_8287(monkeypatch):
    secret = "qa-reviewer-secret-never-print-this"
    username = "jurix-pgm-preview-a1b2c3d4"
    monkeypatch.setenv("JURIX_QA_REVIEWER_PASSWORD", secret)
    monkeypatch.setenv("JURIX_QA_REVIEWER_USERNAME", username)
    command = ["node", "tests/js/document-review-candidate.browser.smoke.mjs"]

    assert qa._allowed_command(command) == ["node.exe", command[1]]
    scoped = qa._command_environment({"JURIX_QA_ONLY": "1"}, command)
    assert scoped["JURIX_QA_REVIEWER_PASSWORD"] == secret
    assert scoped["JURIX_QA_REVIEWER_USERNAME"] == username
    assert scoped["JURIX_QA_BASE_URL"] == "http://127.0.0.1:8287"
    with pytest.raises(ValueError):
        qa._allowed_command(command + ["https://example.com"])


def test_qa_runner_scopes_foundation_browser_credentials_to_temporary_reviewer(monkeypatch):
    secret = "qa-reviewer-secret-never-print-this"
    username = "jurix-pgm-preview-a1b2c3d4"
    monkeypatch.setenv("JURIX_QA_REVIEWER_PASSWORD", secret)
    monkeypatch.setenv("JURIX_QA_REVIEWER_USERNAME", username)
    command = ["node", "tests/js/foundation-check.browser.smoke.mjs"]

    assert qa._allowed_command(command) == ["node.exe", command[1]]
    scoped = qa._command_environment({"JURIX_QA_ONLY": "1"}, command)
    assert scoped["JURIX_QA_REVIEWER_PASSWORD"] == secret
    assert scoped["JURIX_QA_REVIEWER_USERNAME"] == username
    assert scoped["JURIX_QA_BASE_URL"] == "http://127.0.0.1:8287"

    monkeypatch.setenv("JURIX_QA_REVIEWER_USERNAME", "jurix-pgm-smoke-reviewer")
    with pytest.raises(ValueError):
        qa._command_environment({"JURIX_QA_ONLY": "1"}, command)


def test_qa_runner_allows_only_the_authenticated_synthetic_review_browser_test():
    command = ["node", "tests/js/normative-admin-review.browser.test.mjs"]
    assert qa._allowed_command(command) == ["node.exe", *command[1:]]
    with pytest.raises(ValueError):
        qa._allowed_command(command + ["https://example.com"])


def test_qa_runner_allows_only_the_authenticated_synthetic_collections_browser_test():
    command = ["node", "tests/js/normative-collections.browser.test.mjs"]
    assert qa._allowed_command(command) == ["node.exe", *command[1:]]
    with pytest.raises(ValueError):
        qa._allowed_command(command + ["https://example.com"])


def test_command_runner_allows_only_the_runbook_qa_web_server():
    expected = ["python", "manage.py", "runserver", "127.0.0.1:8007", "--noreload"]
    assert qa._allowed_command(expected) == [
        qa.sys.executable,
        "manage.py",
        "runserver",
        "127.0.0.1:8007",
        "--noreload",
    ]
    diagnostic_port = ["python", "manage.py", "runserver", "127.0.0.1:8009", "--noreload"]
    assert qa._allowed_command(diagnostic_port) == [
        qa.sys.executable,
        "manage.py",
        "runserver",
        "127.0.0.1:8009",
        "--noreload",
    ]
    fresh_code_port = ["python", "manage.py", "runserver", "127.0.0.1:8286", "--noreload"]
    assert qa._allowed_command(fresh_code_port) == [
        qa.sys.executable,
        "manage.py",
        "runserver",
        "127.0.0.1:8286",
        "--noreload",
    ]
    isolated_verification_port = ["python", "manage.py", "runserver", "127.0.0.1:8010", "--noreload"]
    assert qa._allowed_command(isolated_verification_port) == [
        qa.sys.executable,
        "manage.py",
        "runserver",
        "127.0.0.1:8010",
        "--noreload",
    ]
    isolated_streaming_port = [
        "python", "manage.py", "runserver", "127.0.0.1:8011", "--noreload"
    ]
    assert qa._allowed_command(isolated_streaming_port) == [
        qa.sys.executable,
        "manage.py",
        "runserver",
        "127.0.0.1:8011",
        "--noreload",
    ]
    isolated_link_verification_port = [
        "python", "manage.py", "runserver", "127.0.0.1:8012", "--noreload"
    ]
    assert qa._allowed_command(isolated_link_verification_port) == [
        qa.sys.executable,
        "manage.py",
        "runserver",
        "127.0.0.1:8012",
        "--noreload",
    ]
    isolated_fresh_code_port = [
        "python", "manage.py", "runserver", "127.0.0.1:8013", "--noreload"
    ]
    assert qa._allowed_command(isolated_fresh_code_port) == [
        qa.sys.executable,
        "manage.py",
        "runserver",
        "127.0.0.1:8013",
        "--noreload",
    ]
    second_isolated_fresh_code_port = [
        "python", "manage.py", "runserver", "127.0.0.1:8014", "--noreload"
    ]
    assert qa._allowed_command(second_isolated_fresh_code_port) == [
        qa.sys.executable,
        "manage.py",
        "runserver",
        "127.0.0.1:8014",
        "--noreload",
    ]
    third_isolated_fresh_code_port = [
        "python", "manage.py", "runserver", "127.0.0.1:8015", "--noreload"
    ]
    assert qa._allowed_command(third_isolated_fresh_code_port) == [
        qa.sys.executable,
        "manage.py",
        "runserver",
        "127.0.0.1:8015",
        "--noreload",
    ]
    fourth_isolated_fresh_code_port = [
        "python", "manage.py", "runserver", "127.0.0.1:8016", "--noreload"
    ]
    assert qa._allowed_command(fourth_isolated_fresh_code_port) == [
        qa.sys.executable,
        "manage.py",
        "runserver",
        "127.0.0.1:8016",
        "--noreload",
    ]
    fifth_isolated_fresh_code_port = [
        "python", "manage.py", "runserver", "127.0.0.1:8017", "--noreload"
    ]
    assert qa._allowed_command(fifth_isolated_fresh_code_port) == [
        qa.sys.executable,
        "manage.py",
        "runserver",
        "127.0.0.1:8017",
        "--noreload",
    ]
    sixth_isolated_fresh_code_port = [
        "python", "manage.py", "runserver", "127.0.0.1:8018", "--noreload"
    ]
    assert qa._allowed_command(sixth_isolated_fresh_code_port) == [
        qa.sys.executable,
        "manage.py",
        "runserver",
        "127.0.0.1:8018",
        "--noreload",
    ]
    seventh_isolated_fresh_code_port = [
        "python", "manage.py", "runserver", "127.0.0.1:8019", "--noreload"
    ]
    assert qa._allowed_command(seventh_isolated_fresh_code_port) == [
        qa.sys.executable,
        "manage.py",
        "runserver",
        "127.0.0.1:8019",
        "--noreload",
    ]
    eighth_isolated_fresh_code_port = [
        "python", "manage.py", "runserver", "127.0.0.1:8020", "--noreload"
    ]
    assert qa._allowed_command(eighth_isolated_fresh_code_port) == [
        qa.sys.executable,
        "manage.py",
        "runserver",
        "127.0.0.1:8020",
        "--noreload",
    ]
    ninth_isolated_fresh_code_port = [
        "python", "manage.py", "runserver", "127.0.0.1:8021", "--noreload"
    ]
    assert qa._allowed_command(ninth_isolated_fresh_code_port) == [
        qa.sys.executable,
        "manage.py",
        "runserver",
        "127.0.0.1:8021",
        "--noreload",
    ]
    tenth_isolated_fresh_code_port = [
        "python", "manage.py", "runserver", "127.0.0.1:8022", "--noreload"
    ]
    assert qa._allowed_command(tenth_isolated_fresh_code_port) == [
        qa.sys.executable,
        "manage.py",
        "runserver",
        "127.0.0.1:8022",
        "--noreload",
    ]
    eleventh_isolated_fresh_code_port = [
        "python", "manage.py", "runserver", "127.0.0.1:8023", "--noreload"
    ]
    assert qa._allowed_command(eleventh_isolated_fresh_code_port) == [
        qa.sys.executable,
        "manage.py",
        "runserver",
        "127.0.0.1:8023",
        "--noreload",
    ]
    twelfth_isolated_fresh_code_port = [
        "python", "manage.py", "runserver", "127.0.0.1:8024", "--noreload"
    ]
    assert qa._allowed_command(twelfth_isolated_fresh_code_port) == [
        qa.sys.executable,
        "manage.py",
        "runserver",
        "127.0.0.1:8024",
        "--noreload",
    ]
    thirteenth_isolated_fresh_code_port = [
        "python", "manage.py", "runserver", "127.0.0.1:8025", "--noreload"
    ]
    assert qa._allowed_command(thirteenth_isolated_fresh_code_port) == [
        qa.sys.executable,
        "manage.py",
        "runserver",
        "127.0.0.1:8025",
        "--noreload",
    ]
    fourteenth_isolated_fresh_code_port = [
        "python", "manage.py", "runserver", "127.0.0.1:8026", "--noreload"
    ]
    assert qa._allowed_command(fourteenth_isolated_fresh_code_port) == [
        qa.sys.executable,
        "manage.py",
        "runserver",
        "127.0.0.1:8026",
        "--noreload",
    ]
    fresh_runtime_verification_port = [
        "python", "manage.py", "runserver", "127.0.0.1:8029", "--noreload"
    ]
    assert qa._allowed_command(fresh_runtime_verification_port) == [
        qa.sys.executable,
        "manage.py",
        "runserver",
        "127.0.0.1:8029",
        "--noreload",
    ]
    current_checkout_verification_port = [
        "python", "manage.py", "runserver", "127.0.0.1:8030", "--noreload"
    ]
    assert qa._allowed_command(current_checkout_verification_port) == [
        qa.sys.executable,
        "manage.py",
        "runserver",
        "127.0.0.1:8030",
        "--noreload",
    ]
    current_pgm_qa_port = [
        "python", "manage.py", "runserver", "127.0.0.1:8040", "--noreload"
    ]
    assert qa._allowed_command(current_pgm_qa_port) == [
        qa.sys.executable,
        "manage.py",
        "runserver",
        "127.0.0.1:8040",
        "--noreload",
    ]
    windows_reserved_range_alternative = [
        "python", "manage.py", "runserver", "127.0.0.1:8280", "--noreload"
    ]
    assert qa._allowed_command(windows_reserved_range_alternative) == [
        qa.sys.executable,
        "manage.py",
        "runserver",
        "127.0.0.1:8280",
        "--noreload",
    ]
    current_overview_qa_port = [
        "python", "manage.py", "runserver", "127.0.0.1:8281", "--noreload"
    ]
    assert qa._allowed_command(current_overview_qa_port) == [
        qa.sys.executable,
        "manage.py",
        "runserver",
        "127.0.0.1:8281",
        "--noreload",
    ]
    fresh_pgm_qa_port = [
        "python", "manage.py", "runserver", "127.0.0.1:8282", "--noreload"
    ]
    assert qa._allowed_command(fresh_pgm_qa_port) == [
        qa.sys.executable,
        "manage.py",
        "runserver",
        "127.0.0.1:8282",
        "--noreload",
    ]
    fresh_title_qa_port = [
        "python", "manage.py", "runserver", "127.0.0.1:8283", "--noreload"
    ]
    assert qa._allowed_command(fresh_title_qa_port) == [
        qa.sys.executable,
        "manage.py",
        "runserver",
        "127.0.0.1:8283",
        "--noreload",
    ]
    current_checkout_qa_port = [
        "python", "manage.py", "runserver", "127.0.0.1:8284", "--noreload"
    ]
    assert qa._allowed_command(current_checkout_qa_port) == [
        qa.sys.executable,
        "manage.py",
        "runserver",
        "127.0.0.1:8284",
        "--noreload",
    ]
    container_audit_web_port = [
        "python", "manage.py", "runserver", "127.0.0.1:8287", "--noreload"
    ]
    assert qa._allowed_command(container_audit_web_port) == [
        qa.sys.executable,
        "manage.py",
        "runserver",
        "127.0.0.1:8287",
        "--noreload",
    ]
    live_rag_qa_port = [
        "python", "manage.py", "runserver", "127.0.0.1:8288", "--noreload"
    ]
    assert qa._allowed_command(live_rag_qa_port) == [
        qa.sys.executable,
        "manage.py",
        "runserver",
        "127.0.0.1:8288",
        "--noreload",
    ]
    current_rag_qa_port = [
        "python", "manage.py", "runserver", "127.0.0.1:8289", "--noreload"
    ]
    assert qa._allowed_command(current_rag_qa_port) == [
        qa.sys.executable,
        "manage.py",
        "runserver",
        "127.0.0.1:8289",
        "--noreload",
    ]
    foundation_fix_qa_port = [
        "python", "manage.py", "runserver", "127.0.0.1:8291", "--noreload"
    ]
    assert qa._allowed_command(foundation_fix_qa_port) == [
        qa.sys.executable,
        "manage.py",
        "runserver",
        "127.0.0.1:8291",
        "--noreload",
    ]
    matter_lookup_qa_port = [
        "python", "manage.py", "runserver", "127.0.0.1:8292", "--noreload"
    ]
    assert qa._allowed_command(matter_lookup_qa_port) == [
        qa.sys.executable,
        "manage.py",
        "runserver",
        "127.0.0.1:8292",
        "--noreload",
    ]
    for unsafe in (
        ["python", "manage.py", "runserver", "127.0.0.1:8006", "--noreload"],
        ["python", "manage.py", "runserver", "127.0.0.1:8029"],
        ["python", "manage.py", "runserver", "127.0.0.1:8031", "--noreload"],
        ["python", "manage.py", "runserver", "0.0.0.0:8009", "--noreload"],
        ["python", "manage.py", "runserver", "0.0.0.0:8007", "--noreload"],
        ["python", "manage.py", "runserver", "127.0.0.1:8007"],
    ):
        with pytest.raises(ValueError):
            qa._allowed_command(unsafe)


def test_pilot_manifest_requires_output_inside_the_isolated_qa_root(tmp_path, monkeypatch):
    qa_root = tmp_path / "qa"
    qa_root.mkdir()
    monkeypatch.setenv("JURIX_QA_ROOT", str(qa_root))
    accepted = [
        "python", "manage.py", "build_pilot_manifest", "--schema-version", "2",
        "--output", str(qa_root / "pilot.jsonl"),
    ]
    assert qa._allowed_command(accepted)[0] == qa.sys.executable
    with pytest.raises(ValueError, match="inside JURIX_QA_ROOT"):
        qa._allowed_command([
            "python", "manage.py", "build_pilot_manifest", "--schema-version", "2",
            "--output", str(tmp_path / "outside.jsonl"),
        ])
    with pytest.raises(ValueError, match="explicit output path"):
        qa._allowed_command(["python", "manage.py", "build_pilot_manifest", "--schema-version", "2"])


def test_command_runner_allows_only_the_bounded_normative_qa_worker_and_dispatcher():
    worker = [
        "python", "-m", "celery", "-A", "config", "worker", "--pool=solo",
        "--concurrency=1", "-Q", "normative_qa", "-l", "warning",
    ]
    assert qa._allowed_command(worker)[0] == qa.sys.executable
    with pytest.raises(ValueError):
        qa._allowed_command(worker[:-4] + ["-Q", "default", "-l", "warning"])
    assert qa._allowed_command([
        "python", "manage.py", "run_normative_qa_pipeline", "--norma-id", "8",
        "--max-nodes", "10", "--max-items", "10",
    ])[0] == qa.sys.executable
    assert qa._allowed_command([
        "python", "manage.py", "extract_archive_candidate_qa", "--document-id",
        "eaa13513-6cfc-4edf-8027-c6a7cc6d70b7",
    ])[0] == qa.sys.executable
    assert qa._allowed_command([
        "python", "manage.py", "extract_archive_candidate_qa", "--document-id",
        "eaa13513-6cfc-4edf-8027-c6a7cc6d70b7", "--max-ocr-pages", "0",
        "--ocr-timeout-seconds", "15",
    ])[0] == qa.sys.executable
    assert qa._allowed_command([
        "python", "manage.py", "extract_archive_candidate_qa", "--document-id",
        "eaa13513-6cfc-4edf-8027-c6a7cc6d70b7", "--max-ocr-pages", "10",
        "--ocr-timeout-seconds", "30",
    ])[0] == qa.sys.executable
    assert qa._allowed_command([
        "python", "manage.py", "extract_archive_candidate_qa", "--document-id",
        "cb810b42-ecea-4cbc-870a-b2581c30df6c", "--max-ocr-pages", "1",
        "--ocr-page", "7",
    ])[0] == qa.sys.executable
    for args in (
        ["--max-ocr-pages", "1", "--ocr-page", "6"],
        ["--max-ocr-pages", "2", "--ocr-page", "7"],
    ):
        with pytest.raises(ValueError, match="explicit OCR is restricted"):
            qa._allowed_command([
                "python", "manage.py", "extract_archive_candidate_qa", "--document-id",
                "cb810b42-ecea-4cbc-870a-b2581c30df6c", *args,
            ])
    with pytest.raises(ValueError, match="explicit OCR is restricted"):
        qa._allowed_command([
            "python", "manage.py", "extract_archive_candidate_qa", "--document-id",
            "eaa13513-6cfc-4edf-8027-c6a7cc6d70b7", "--max-ocr-pages", "1",
            "--ocr-page", "7",
        ])
    with pytest.raises(ValueError, match="valid UUID"):
        qa._allowed_command([
            "python", "manage.py", "extract_archive_candidate_qa", "--document-id", "not-a-uuid",
        ])
    with pytest.raises(ValueError, match="unsupported flags"):
        qa._allowed_command([
            "python", "manage.py", "extract_archive_candidate_qa", "--document-id",
            "eaa13513-6cfc-4edf-8027-c6a7cc6d70b7", "--all",
        ])
    for extra in (
        ["--max-ocr-pages", "11"],
        ["--max-ocr-pages", "-1"],
        ["--ocr-timeout-seconds", "31"],
        ["--ocr-timeout-seconds", "0"],
        ["--max-ocr-pages", "not-an-integer"],
        ["--max-ocr-pages", "0", "--max-ocr-pages", "1"],
    ):
        with pytest.raises(ValueError):
            qa._allowed_command([
                "python", "manage.py", "extract_archive_candidate_qa", "--document-id",
                "eaa13513-6cfc-4edf-8027-c6a7cc6d70b7", *extra,
            ])


def test_audit_compose_worker_consumes_the_normative_qa_queue():
    compose_path = MODULE_PATH.parents[1] / "docker-compose.audit.yml"
    compose = compose_path.read_text(encoding="utf-8")

    assert (
        "command: celery -A config worker -l warning --pool=solo --concurrency=1 "
        "--queues normative_qa,celery"
    ) in compose
    with pytest.raises(ValueError):
        qa._allowed_command([
            "python", "manage.py", "run_normative_qa_pipeline", "--norma-id", "8", "--all",
        ])


def test_archive_batch_extraction_guard_enforces_qa_sized_batches_and_explicit_mode():
    base = ["python", "manage.py", "extract_archive_candidates_batch_qa"]
    assert qa._allowed_command(base + ["--dry-run", "--batch-size", "10"])[0] == qa.sys.executable
    assert qa._allowed_command(base + ["--dry-run", "--resume", "--batch-size", "1"])[0] == qa.sys.executable
    assert qa._allowed_command(base + ["--apply", "--resume", "--batch-size", "5"])[0] == qa.sys.executable
    assert qa._allowed_command(
        base + ["--dry-run", "--publication-order", "--batch-size", "10"]
    )[0] == qa.sys.executable
    assert qa._allowed_command(
        base + ["--apply", "--publication-order", "--resume", "--batch-size", "10"]
    )[0] == qa.sys.executable
    assert qa._allowed_command(
        base + ["--dry-run", "--all-publication-order", "--batch-size", "1"]
    )[0] == qa.sys.executable
    assert qa._allowed_command(
        base + ["--apply", "--all-publication-order", "--resume", "--batch-size", "10"]
    )[0] == qa.sys.executable
    assert qa._allowed_command(
        base + ["--dry-run", "--all-publication-order", "--new-snapshot", "--batch-size", "10"]
    )[0] == qa.sys.executable
    assert qa._container_storage_command(
        [*base, "--apply", "--publication-order", "--batch-size", "10"]
    ) is None
    assert qa._container_storage_command(
        [*base, "--dry-run", "--all-publication-order", "--batch-size", "1"]
    ) is None
    assert qa._container_storage_command([*base, "--apply", "--batch-size", "10"]) is not None
    for options in (
        [],
        ["--apply", "--dry-run"],
        ["--apply", "--resume", "--dry-run"],
        ["--apply", "--batch-size", "11"],
        ["--dry-run", "--batch-size", "0"],
        ["--apply", "--resume", "--all"],
        ["--resume"],
        ["--dry-run", "--publication-order", "--publication-order"],
        ["--dry-run", "--all-publication-order", "--all-publication-order"],
        ["--dry-run", "--publication-order", "--all-publication-order"],
        ["--dry-run", "--new-snapshot"],
        ["--dry-run", "--all-publication-order", "--new-snapshot", "--new-snapshot"],
    ):
        with pytest.raises(ValueError):
            qa._allowed_command(base + options)


def test_archive_ocr_resume_guard_requires_one_document_and_tiny_explicit_batch():
    base = ["python", "manage.py", "resume_archive_ocr_qa"]
    document_id = "eaa13513-6cfc-4edf-8027-c6a7cc6d70b7"
    assert qa._allowed_command(
        base + ["--document-id", document_id, "--dry-run", "--batch-pages", "10"]
    )[0] == qa.sys.executable
    assert qa._allowed_command(
        base + ["--document-id", document_id, "--pages", "69", "70", "--dry-run", "--batch-pages", "2"]
    )[0] == qa.sys.executable
    assert qa._allowed_command(
        base + [
            "--document-id", document_id, "--pages", "70", "--retry-unreadable",
            "--dry-run", "--batch-pages", "1",
        ]
    )[0] == qa.sys.executable
    assert qa._allowed_command(
        base + ["--document-id", document_id, "--apply", "--batch-pages", "1"]
    )[0] == qa.sys.executable
    assert qa._allowed_command(base + ["--pick-next", "--dry-run"])[0] == qa.sys.executable
    assert qa._allowed_command(base + ["--pick-unreadable", "--dry-run"])[0] == qa.sys.executable
    assert qa._allowed_command(base + ["--pick-blank", "--dry-run"])[0] == qa.sys.executable
    assert qa._allowed_command(
        base + ["--document-id", document_id, "--reclassify-blank", "--dry-run"]
    )[0] == qa.sys.executable
    for options in (
        ["--document-id", document_id, "--dry-run", "--apply"],
        ["--document-id", "invalid", "--dry-run"],
        ["--document-id", document_id, "--dry-run", "--batch-pages", "11"],
        ["--document-id", document_id, "--dry-run", "--all"],
        ["--document-id", document_id, "--pages", "69", "70", "--dry-run", "--batch-pages", "1"],
        ["--document-id", document_id, "--pages", "69", "--pick-unreadable", "--dry-run"],
        ["--document-id", document_id, "--pages", "0", "--dry-run"],
        ["--document-id", document_id, "--pages", "69", "69", "--dry-run"],
        ["--pick-next", "--pages", "69", "--dry-run"],
        ["--document-id", document_id, "--pages", "sixty-nine", "--dry-run"],
        ["--dry-run"],
        ["--pick-next", "--apply"],
        ["--document-id", document_id, "--pick-next", "--dry-run"],
        ["--pick-next", "--dry-run", "--batch-pages", "0"],
        ["--pick-unreadable", "--apply"],
        ["--pick-unreadable", "--dry-run", "--retry-unreadable"],
        ["--pick-blank", "--apply"],
        ["--pick-blank", "--dry-run", "--retry-unreadable"],
        ["--document-id", document_id, "--pick-blank", "--dry-run"],
        ["--pick-next", "--dry-run", "--retry-unreadable"],
        ["--pick-next", "--pick-unreadable", "--dry-run"],
        ["--pick-unreadable", "--reclassify-blank", "--dry-run"],
        ["--document-id", document_id, "--retry-unreadable", "--reclassify-blank", "--apply"],
    ):
        with pytest.raises(ValueError):
            qa._allowed_command(base + options)


def test_archive_extraction_coverage_diagnostic_is_read_only_and_accepts_no_options():
    command = ["python", "manage.py", "inspect_archive_extraction_coverage_qa"]
    assert qa._allowed_command(command) == [qa.sys.executable, *command[1:]]
    with pytest.raises(ValueError, match="accepts no options"):
        qa._allowed_command(command + ["--all"])


def test_ctm_article20_timeline_diagnostic_is_read_only_and_accepts_no_options():
    command = ["python", "manage.py", "inspect_ctm_article20_timeline_qa"]
    assert qa._allowed_command(command) == [qa.sys.executable, *command[1:]]
    with pytest.raises(ValueError, match="accepts no options"):
        qa._allowed_command(command + ["--apply"])


def test_pgm_demo_readiness_diagnostic_is_read_only_and_accepts_no_options():
    command = ["python", "manage.py", "inspect_pgm_demo_readiness_qa"]
    assert qa._allowed_command(command) == [qa.sys.executable, *command[1:]]
    with pytest.raises(ValueError, match="accepts no options"):
        qa._allowed_command(command + ["--apply"])


def test_archive_search_profiler_is_fixed_and_accepts_no_options():
    command = ["python", "scripts/profile_archive_search_qa.py"]
    assert qa._allowed_command(command) == [qa.sys.executable, *command[1:]]
    with pytest.raises(ValueError, match="not on the QA allowlist"):
        qa._allowed_command(command + ["--database", "production"])


def test_file_backed_archive_commands_run_inside_the_qa_container_volume():
    args = [
        "python", "manage.py", "resume_archive_ocr_qa",
        "--pick-unreadable", "--dry-run", "--batch-pages", "1",
    ]
    assert qa._allowed_command(args)[0] == qa.sys.executable
    assert qa._container_storage_command(args) == [
        "docker", "compose", "-p", "jurix-normative-qa",
        "-f", str(qa.ROOT / "docker-compose.audit.yml"),
        "exec", "-T", "web", "python", "manage.py",
        *args[2:],
    ]
    assert qa._container_storage_command(
        ["python", "manage.py", "inspect_archive_extraction_coverage_qa"]
    ) is not None
    assert qa._container_storage_command(["python", "manage.py", "check"]) is None
    assert qa._container_storage_command(
        ["python", "manage.py", "stage_normative_corpus", "--dry-run"]
    ) is None


def test_ctm_2021_extraction_uses_the_host_qa_volume_that_contains_its_blob():
    args = [
        "python", "manage.py", "extract_archive_candidate_qa",
        "--document-id", "a68fdb23-c0aa-4082-8871-fe99096847b9",
        "--max-ocr-pages", "0", "--ocr-timeout-seconds", "15",
    ]
    assert qa._allowed_command(args)[0] == qa.sys.executable
    assert qa._container_storage_command(args) is None


def test_lp275_extraction_uses_the_host_qa_volume_that_contains_its_blob():
    args = [
        "python", "manage.py", "extract_archive_candidate_qa",
        "--document-id", "8dea863e-e736-452e-8ca6-288f6061d239",
        "--max-ocr-pages", "0", "--ocr-timeout-seconds", "15",
    ]
    assert qa._allowed_command(args)[0] == qa.sys.executable
    assert qa._container_storage_command(args) is None


def test_lc258_sapl_ocr_resume_stays_on_host_storage_used_for_staging():
    args = [
        "python", "manage.py", "resume_archive_ocr_qa",
        "--document-id", "00c841d2-4b08-42a3-80b1-f018b1e86d43",
        "--pages", "11", "12", "13", "14", "15", "16",
        "--apply", "--batch-pages", "6",
    ]
    assert qa._allowed_command(args)[0] == qa.sys.executable
    assert qa._container_storage_command(args) is None


def test_missing_archive_blob_restore_is_bounded_and_confined_to_qa_inventory(tmp_path, monkeypatch):
    qa_root = tmp_path / "qa"
    qa_root.mkdir()
    archive = tmp_path / "source.zip"
    archive.touch()
    manifest = qa_root / "inventory.jsonl"
    monkeypatch.setenv("JURIX_QA_ROOT", str(qa_root))
    base = [
        "python", "manage.py", "restore_missing_archive_blobs_qa",
        "--archive", str(archive), "--manifest", str(manifest), "--limit", "4",
    ]

    assert qa._allowed_command(base + ["--dry-run"])[0] == qa.sys.executable
    with pytest.raises(ValueError, match="TEMP storage may differ from the Docker volume"):
        qa._allowed_command(base + ["--apply"])
    with pytest.raises(ValueError, match="exactly one mode"):
        qa._allowed_command(base)
    with pytest.raises(ValueError, match="exactly one mode"):
        qa._allowed_command(base + ["--apply", "--dry-run"])
    with pytest.raises(ValueError, match="between 1 and 10"):
        qa._allowed_command(base[:-1] + ["11", "--dry-run"])
    with pytest.raises(ValueError, match="inside JURIX_QA_ROOT"):
        qa._allowed_command(
            base[:base.index("--manifest") + 1]
            + [str(tmp_path / "outside.jsonl"), "--dry-run"]
        )
    with pytest.raises(ValueError, match="outside JURIX_QA_ROOT"):
        qa._allowed_command(
            base[:base.index("--archive") + 1]
            + [str(qa_root / "source.zip"), "--manifest", str(manifest), "--dry-run"]
        )
    with pytest.raises(ValueError, match="unsupported flag"):
        qa._allowed_command(base + ["--accept", "--dry-run"])


def test_corpus_staging_command_requires_allowlisted_flags_and_qa_manifest(tmp_path, monkeypatch):
    qa_root = tmp_path / "qa"
    qa_root.mkdir()
    monkeypatch.setenv("JURIX_QA_ROOT", str(qa_root))
    accepted = [
        "python", "manage.py", "stage_normative_corpus",
        "--archive", str(tmp_path / "source.zip"),
        "--manifest", str(qa_root / "inventory.jsonl"),
        "--batch-size", "10", "--byte-budget", "1000000",
        "--time-budget-seconds", "60", "--apply",
    ]
    assert qa._allowed_command(accepted)[0] == qa.sys.executable
    with pytest.raises(ValueError, match="inside JURIX_QA_ROOT"):
        qa._allowed_command(accepted[:accepted.index("--manifest") + 1] + [str(tmp_path / "outside.jsonl")])
    with pytest.raises(ValueError, match="not on the QA allowlist"):
        qa._allowed_command(accepted + ["--max-sources", "999"])
    assert qa._allowed_command(accepted[:-1] + ["--dry-run"])[0] == qa.sys.executable
    with pytest.raises(ValueError, match="explicit archive and manifest"):
        qa._allowed_command(["python", "manage.py", "stage_normative_corpus", "--apply"])


def test_django_settings_reject_a_database_url_outside_the_audit_service():
    env = os.environ.copy()
    env.update(
        {
            "JURIX_QA_ONLY": "1",
            "JURIX_QA_ROOT": str(Path(os.environ["JURIX_QA_ROOT"]).resolve()),
            "DJANGO_SKIP_DOTENV": "1",
            "DJANGO_SETTINGS_MODULE": "config.settings_normative_qa",
            "DATABASE_URL": "postgresql://user:pass@127.0.0.1:5432/production",
            "REDIS_URL": qa.REDIS_URL,
            "CACHE_REDIS_URL": qa.CACHE_REDIS_URL,
        }
    )
    result = subprocess.run(
        [sys.executable, "-c", "import config.settings_normative_qa"],
        cwd=qa.ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert "only accept the dedicated local audit PostgreSQL target" in result.stderr


def test_django_settings_allow_a_separate_cache_namespace_for_qa_test_runs():
    env = os.environ.copy()
    env.update(
        {
            "JURIX_QA_ONLY": "1",
            "JURIX_QA_ROOT": str(Path(os.environ["JURIX_QA_ROOT"]).resolve()),
            "DJANGO_SKIP_DOTENV": "1",
            "DJANGO_SETTINGS_MODULE": "config.settings_normative_qa",
            "DJANGO_SECRET_KEY": "jurix-normative-qa-test-only",
            "DEBUG": "1",
            "DATABASE_URL": qa.DATABASE_URL,
            "REDIS_URL": qa.REDIS_URL,
            "CACHE_REDIS_URL": qa.CACHE_REDIS_URL,
            "JURIX_QA_CACHE_PREFIX": "jurix-test-run-isolated",
        }
    )
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from django.conf import settings; print(settings.CACHES['default']['KEY_PREFIX'])",
        ],
        cwd=qa.ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "jurix-test-run-isolated"


def test_qa_runner_limits_sapl_candidate_staging_to_exact_promulgated_records():
    base = ["python", "manage.py", "stage_sapl_normative_candidate_qa"]
    for sapl_id in ("9406", "1160", "4052", "8823", "925", "254", "3666", "6817"):
        dry_run = base + ["--sapl-id", sapl_id]
        apply = dry_run + ["--apply"]
        assert qa._allowed_command(dry_run) == [qa.sys.executable, *dry_run[1:]]
        assert qa._allowed_command(apply) == [qa.sys.executable, *apply[1:]]
    for sapl_id in ("9406", "4052", "1160", "254"):
        inspect = base + ["--sapl-id", sapl_id, "--inspect-existing"]
        assert qa._allowed_command(inspect) == [qa.sys.executable, *inspect[1:]]
    for unsafe in (
        base + ["--sapl-id", "3667"],
        base + ["--sapl-id", "3666", "--force"],
        base + ["--sapl-id", "3666", "--apply", "--sapl-id", "3666"],
    ):
        with pytest.raises(ValueError, match="exact QA allowlist"):
            qa._allowed_command(unsafe)


def test_qa_runner_allows_only_exact_synthetic_lc198_identity_isolation():
    base = [
        "python", "manage.py", "isolate_synthetic_norma_identity_qa",
        "--norma-id", "7",
        "--expected-identity-key", "BR-RN-NATAL|lei_complementar|municipal_lc|198|2021",
        "--expected-tipo", "Lei Complementar",
        "--expected-numero", "198",
        "--expected-ano", "2021",
    ]
    assert qa._allowed_command(base)[0] == qa.sys.executable
    assert qa._allowed_command(base + ["--apply"])[0] == qa.sys.executable
    with pytest.raises(ValueError):
        qa._allowed_command(base[:-1] + ["2004"])
    with pytest.raises(ValueError):
        qa._allowed_command(base + ["--force"])
