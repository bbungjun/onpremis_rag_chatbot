import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.eval_intent import load_cases, summarize  # noqa: E402


def write_jsonl(tmp_path: Path, rows: list[dict]) -> Path:
    path = tmp_path / "cases.jsonl"
    body = "\n".join(json.dumps(row, ensure_ascii=False) for row in rows)
    path.write_text(f"{body}\n\n", encoding="utf-8")
    return path


def test_load_cases_reads_rows_and_skips_blank_lines(tmp_path):
    path = write_jsonl(
        tmp_path,
        [
            {"id": "q01", "question": "연차 신청은 며칠 전까지 해야 하나요?", "type": "일상어"},
            {"id": "q02", "question": "제39조의 연차 발생 기준은?", "type": "조항용어"},
        ],
    )

    cases = load_cases(path)

    assert [case["id"] for case in cases] == ["q01", "q02"]


def test_load_cases_rejects_row_without_question(tmp_path):
    path = write_jsonl(tmp_path, [{"id": "q01", "type": "일상어"}])

    with pytest.raises(ValueError, match="question"):
        load_cases(path)


def test_summarize_counts_intents_and_general_qa_rate():
    cases = [
        {"id": "q01", "question": "연차 신청은 며칠 전까지 해야 하나요?", "type": "일상어"},
        {"id": "q02", "question": "재택근무 승인 절차는 어떻게 되나요?", "type": "일상어"},
        {"id": "q03", "question": "징계 종류에는 뭐가 있나요?", "type": "조항용어"},
    ]

    report = summarize(cases)

    assert report.total == 3
    assert report.intent_counts["deadline_lookup"] == 1
    assert report.intent_counts["procedure_lookup"] == 1
    assert report.intent_counts["general_qa"] == 1
    assert report.general_qa_rate == pytest.approx(1 / 3)


def test_summarize_groups_by_type():
    cases = [
        {"id": "q01", "question": "징계 종류에는 뭐가 있나요?", "type": "일상어"},
        {"id": "q02", "question": "연차 신청은 며칠 전까지 해야 하나요?", "type": "조항용어"},
    ]

    report = summarize(cases)

    assert report.by_type["일상어"].general_qa_rate == pytest.approx(1.0)
    assert report.by_type["조항용어"].general_qa_rate == pytest.approx(0.0)


def test_summarize_lists_general_qa_cases():
    cases = [
        {"id": "q01", "question": "징계 종류에는 뭐가 있나요?", "type": "일상어"},
        {"id": "q02", "question": "연차 신청은 며칠 전까지 해야 하나요?", "type": "일상어"},
    ]

    report = summarize(cases)

    assert [case["id"] for case in report.general_qa_cases] == ["q01"]


def test_summarize_handles_empty_input():
    report = summarize([])

    assert report.total == 0
    assert report.general_qa_rate == 0.0
