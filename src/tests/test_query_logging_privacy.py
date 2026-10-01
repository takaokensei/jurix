"""Ensure operational logs never contain user prompts or provider secrets."""

import ast
import logging
from pathlib import Path

from src.observability.safe_logging import log_exception_safely

ROOT = Path(__file__).resolve().parents[2]
SENSITIVE_MODULES = (
    "src/processing/rag_service.py",
    "src/processing/cache_service.py",
    "src/apps/legislation/api_search.py",
    "src/apps/legislation/views.py",
)
SENSITIVE_NAMES = {"question", "query", "query_text", "clean_question", "prompt", "api_key"}


def test_sensitive_logs_do_not_interpolate_prompt_values_or_tracebacks():
    for relative_path in SENSITIVE_MODULES:
        tree = ast.parse((ROOT / relative_path).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            if not isinstance(node.func.value, ast.Name) or node.func.value.id != "logger":
                continue

            assert node.func.attr != "exception", f"Unsafe traceback log in {relative_path}"
            assert not any(
                keyword.arg == "exc_info" for keyword in node.keywords
            ), f"Unsafe traceback locals in {relative_path}"

            if node.args and isinstance(node.args[0], ast.JoinedStr):
                for value in node.args[0].values:
                    if isinstance(value, ast.FormattedValue):
                        names = {
                            item.id for item in ast.walk(value.value) if isinstance(item, ast.Name)
                        }
                        assert (
                            not names & SENSITIVE_NAMES
                        ), f"Prompt value interpolated into log in {relative_path}:{node.lineno}"

            for argument in node.args[1:]:
                assert not (
                    isinstance(argument, ast.Name) and argument.id in SENSITIVE_NAMES
                ), f"Prompt passed as log value in {relative_path}:{node.lineno}"


def test_safe_exception_log_omits_prompt_and_provider_key(caplog):
    prompt = "SENTINEL_CONFIDENCIAL_8205"
    key = "SENTINEL_API_KEY_NAO_LOGAR"
    logger = logging.getLogger("jurix.privacy.test")

    with caplog.at_level(logging.DEBUG, logger=logger.name):
        try:
            raise RuntimeError(f"provider failed for {prompt}; authorization={key}")
        except RuntimeError as error:
            log_exception_safely(logger, "Provider request failed", error)

    assert "Provider request failed" in caplog.text
    assert "RuntimeError" in caplog.text
    assert prompt not in caplog.text
    assert key not in caplog.text
