import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.eval_intent import (  # noqa: E402
    evaluate_accuracy,
    load_cases,
    load_gold_labels,
    print_accuracy_report,
    summarize,
)


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


def test_load_gold_labels_reads_valid_rows_and_rejects_duplicates(tmp_path):
    path = write_jsonl(
        tmp_path,
        [
            {"id": "q01", "expected_intent": "deadline_lookup"},
            {"id": "q02", "expected_intent": "general_qa"},
        ],
    )

    assert load_gold_labels(path) == {
        "q01": "deadline_lookup",
        "q02": "general_qa",
    }

    duplicate = write_jsonl(
        tmp_path,
        [
            {"id": "q01", "expected_intent": "deadline_lookup"},
            {"id": "q01", "expected_intent": "general_qa"},
        ],
    )
    with pytest.raises(ValueError, match="duplicate gold id.*q01"):
        load_gold_labels(duplicate)


@pytest.mark.parametrize(
    "row",
    [
        {"expected_intent": "deadline_lookup"},
        {"id": "q01"},
        {"id": "q01", "expected_intent": "unknown"},
    ],
)
def test_load_gold_labels_rejects_invalid_rows(tmp_path, row):
    path = write_jsonl(tmp_path, [row])

    with pytest.raises(ValueError):
        load_gold_labels(path)


def test_evaluate_accuracy_reports_confusion_types_and_errors(monkeypatch):
    from types import SimpleNamespace

    import scripts.eval_intent as evaluator

    predicted = {
        "deadline question": "deadline_lookup",
        "wrong procedure": "eligibility_check",
        "general question": "general_qa",
    }
    monkeypatch.setattr(
        evaluator,
        "interpret_question",
        lambda question: SimpleNamespace(intent=predicted[question]),
    )
    cases = [
        {"id": "q01", "question": "deadline question", "type": "일상어"},
        {"id": "q02", "question": "wrong procedure", "type": "구어체"},
        {"id": "q03", "question": "general question", "type": "구어체"},
    ]
    gold = {
        "q01": "deadline_lookup",
        "q02": "procedure_lookup",
        "q03": "general_qa",
    }

    report = evaluate_accuracy(cases, gold)

    assert report.total == 3
    assert report.correct == 2
    assert report.accuracy == pytest.approx(2 / 3)
    assert report.by_type["일상어"].accuracy == pytest.approx(1.0)
    assert report.by_type["구어체"].accuracy == pytest.approx(0.5)
    assert report.confusion_matrix["procedure_lookup"]["eligibility_check"] == 1
    assert report.confusion_matrix["general_qa"]["general_qa"] == 1
    assert report.errors == [
        {
            "id": "q02",
            "type": "구어체",
            "question": "wrong procedure",
            "expected_intent": "procedure_lookup",
            "predicted_intent": "eligibility_check",
        }
    ]


def test_evaluate_accuracy_rejects_missing_gold_and_duplicate_case_ids():
    case = {"id": "q01", "question": "연차 신청은 언제까지 하나요?", "type": "일상어"}

    with pytest.raises(ValueError, match="missing gold label.*q01"):
        evaluate_accuracy([case], {})
    with pytest.raises(ValueError, match="duplicate case id.*q01"):
        evaluate_accuracy([case, case], {"q01": "deadline_lookup"})


def test_print_accuracy_report_includes_matrix_and_optional_errors(capsys, monkeypatch):
    from types import SimpleNamespace

    import scripts.eval_intent as evaluator

    monkeypatch.setattr(
        evaluator,
        "interpret_question",
        lambda question: SimpleNamespace(intent="eligibility_check"),
    )
    report = evaluate_accuracy(
        [{"id": "q01", "question": "출장비 정산 언제까지?", "type": "오타"}],
        {"q01": "deadline_lookup"},
    )

    print_accuracy_report(report, list_errors=True)

    output = capsys.readouterr().out
    assert "분류 정확도: 0/1 (0.0%)" in output
    assert "혼동 행렬" in output
    assert "deadline_lookup -> eligibility_check: 1" in output
    assert "[q01] expected=deadline_lookup predicted=eligibility_check" in output


def test_committed_gold_labels_cover_current_evaluation_cases_exactly():
    root = Path(__file__).resolve().parents[1]
    cases = load_cases(root / "datasets/eval/qa_set.jsonl") + load_cases(
        root / "datasets/eval/intent_robustness.jsonl"
    )
    labels = load_gold_labels(root / "datasets/eval/intent_gold.jsonl")
    case_ids = [case["id"] for case in cases]

    assert len(cases) == 98
    assert len(case_ids) == len(set(case_ids))
    assert set(labels) == set(case_ids)
