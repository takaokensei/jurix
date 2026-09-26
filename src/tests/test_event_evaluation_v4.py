import json
from pathlib import Path

import pytest

from src.processing.event_evaluation import ACTIONS, load_cases


def test_action_contract_is_closed():
    assert ACTIONS == (
        "REVOGA", "ALTERA", "ADICIONA", "SUBSTITUI", "REGULAMENTA", "REFERENCIA"
    )


def test_load_cases_normalizes_actions(tmp_path: Path):
    path = tmp_path / "cases.jsonl"
    path.write_text(json.dumps({"case_id": "a", "norma_id": 1, "gold_actions": ["altera"]}) + "\n")
    assert load_cases(path)[0].gold_actions == ("ALTERA",)


def test_load_cases_rejects_unknown_actions(tmp_path: Path):
    path = tmp_path / "cases.jsonl"
    path.write_text(json.dumps({"case_id": "a", "norma_id": 1, "gold_actions": ["FOO"]}) + "\n")
    with pytest.raises(ValueError):
        load_cases(path)
