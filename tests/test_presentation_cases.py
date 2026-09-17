import json
from pathlib import Path

import pytest

from app.presentation_cases import load_demo_cases


def write_cases(path: Path, cases: list[dict]) -> None:
    path.write_text(json.dumps({"cases": cases}, ensure_ascii=False), encoding="utf-8")


def valid_case() -> dict:
    return {
        "id": "leave-advance",
        "question": "연차 신청은 며칠 전까지 해야 하나요?",
        "filters": {"department": "hr", "category": "leave"},
    }


def test_load_demo_cases_returns_question_only_cases(tmp_path):
    path = tmp_path / "demo_cases.json"
    write_cases(path, [valid_case()])

    payload = load_demo_cases(path)

    assert payload["cases"] == [valid_case()]


def test_load_demo_cases_rejects_missing_filters(tmp_path):
    case = valid_case()
    del case["filters"]
    path = tmp_path / "demo_cases.json"
    write_cases(path, [case])

    with pytest.raises(ValueError, match="filters"):
        load_demo_cases(path)


def test_repository_cases_contain_questions_without_stored_model_answers():
    cases = load_demo_cases()["cases"]

    assert cases
    assert all(set(case) == {"id", "question", "filters"} for case in cases)
