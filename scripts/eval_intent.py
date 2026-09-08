"""의도 분류 커버리지 측정.

`app.question_interpreter`는 마커 문자열 포함 검사로 intent 를 정한다. 마커에 걸리지
않으면 GENERAL_QA 가 되고, 그 경우 canonical_question 에 답변 지시문이 붙지 않는다.
즉 GENERAL_QA 비율이 곧 "지시문 보강을 못 받는 질문의 비율"이다.

검색에는 영향이 없다(retrieval_question 은 그대로 나간다). 그래서 이 수치는
검색 품질이 아니라 답변 지시 커버리지를 재는 것이다.

사용:
    python scripts/eval_intent.py datasets/eval/qa_set.jsonl
    python scripts/eval_intent.py datasets/eval/*.jsonl --list
    python scripts/eval_intent.py datasets/eval/qa_set.jsonl \
        datasets/eval/intent_robustness.jsonl \
        --gold datasets/eval/intent_gold.jsonl --list-errors
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.question_interpreter import (  # noqa: E402
    DEADLINE_LOOKUP,
    ELIGIBILITY_CHECK,
    GENERAL_QA,
    PROCEDURE_LOOKUP,
    REQUIREMENT_LOOKUP,
    interpret_question,
)

INTENTS = (
    DEADLINE_LOOKUP,
    ELIGIBILITY_CHECK,
    PROCEDURE_LOOKUP,
    REQUIREMENT_LOOKUP,
    GENERAL_QA,
)


@dataclass(frozen=True)
class IntentStats:
    """한 그룹(전체 또는 type 하나)의 분류 결과 요약."""

    total: int
    intent_counts: dict[str, int]
    general_qa_rate: float


@dataclass(frozen=True)
class Report:
    """측정 결과 전체."""

    total: int
    intent_counts: dict[str, int]
    general_qa_rate: float
    by_type: dict[str, IntentStats] = field(default_factory=dict)
    general_qa_cases: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class AccuracyStats:
    """한 그룹의 gold-label 정확도."""

    total: int
    correct: int
    accuracy: float


@dataclass(frozen=True)
class AccuracyReport:
    """gold label과 실제 분류 결과의 비교."""

    total: int
    correct: int
    accuracy: float
    by_type: dict[str, AccuracyStats] = field(default_factory=dict)
    confusion_matrix: dict[str, dict[str, int]] = field(default_factory=dict)
    errors: list[dict[str, str]] = field(default_factory=list)


def load_cases(path: str | Path) -> list[dict[str, Any]]:
    """jsonl 평가 파일을 읽는다. 빈 줄은 건너뛰고, question 이 없으면 실패한다."""
    cases: list[dict[str, Any]] = []
    text = Path(path).read_text(encoding="utf-8")
    for line_no, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if not stripped:
            continue
        row = json.loads(stripped)
        if not row.get("question"):
            raise ValueError(f"{path}:{line_no} row is missing 'question'")
        cases.append(row)
    return cases


def load_gold_labels(path: str | Path) -> dict[str, str]:
    """별도로 검토한 intent gold JSONL을 읽고 ID와 라벨을 검증한다."""
    labels: dict[str, str] = {}
    text = Path(path).read_text(encoding="utf-8")
    for line_no, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if not stripped:
            continue
        row = json.loads(stripped)
        case_id = row.get("id")
        expected = row.get("expected_intent")
        if not isinstance(case_id, str) or not case_id.strip():
            raise ValueError(f"{path}:{line_no} gold row is missing a non-empty 'id'")
        if case_id in labels:
            raise ValueError(f"{path}:{line_no} duplicate gold id {case_id!r}")
        if expected not in INTENTS:
            raise ValueError(
                f"{path}:{line_no} expected_intent must be one of {', '.join(INTENTS)}, "
                f"got {expected!r}"
            )
        labels[case_id] = expected
    return labels


def summarize(cases: list[dict[str, Any]]) -> Report:
    """각 질문을 분류하고 intent 분포와 GENERAL_QA 비율을 집계한다."""
    overall: Counter[str] = Counter()
    grouped: defaultdict[str, Counter[str]] = defaultdict(Counter)
    general_qa_cases: list[dict[str, Any]] = []

    for case in cases:
        intent = interpret_question(case["question"]).intent
        overall[intent] += 1
        grouped[case.get("type", "unknown")][intent] += 1
        if intent == GENERAL_QA:
            general_qa_cases.append(case)

    return Report(
        total=len(cases),
        intent_counts=dict(overall),
        general_qa_rate=_rate(overall[GENERAL_QA], len(cases)),
        by_type={name: _stats(counts) for name, counts in grouped.items()},
        general_qa_cases=general_qa_cases,
    )


def evaluate_accuracy(cases: list[dict[str, Any]], gold_labels: dict[str, str]) -> AccuracyReport:
    """현재 분류를 별도 gold와 비교해 정확도와 confusion matrix를 만든다."""
    seen_ids: set[str] = set()
    correct = 0
    grouped_totals: Counter[str] = Counter()
    grouped_correct: Counter[str] = Counter()
    confusion: dict[str, Counter[str]] = {intent: Counter() for intent in INTENTS}
    errors: list[dict[str, str]] = []

    for case in cases:
        case_id = case.get("id")
        if not isinstance(case_id, str) or not case_id.strip():
            raise ValueError("evaluated case is missing a non-empty 'id'")
        if case_id in seen_ids:
            raise ValueError(f"duplicate case id {case_id!r}")
        seen_ids.add(case_id)
        if case_id not in gold_labels:
            raise ValueError(f"missing gold label for case id {case_id!r}")

        expected = gold_labels[case_id]
        if expected not in INTENTS:
            raise ValueError(f"invalid gold label for case id {case_id!r}: {expected!r}")
        predicted = interpret_question(case["question"]).intent
        case_type = str(case.get("type", "unknown"))
        grouped_totals[case_type] += 1
        confusion[expected][predicted] += 1

        if predicted == expected:
            correct += 1
            grouped_correct[case_type] += 1
        else:
            errors.append(
                {
                    "id": case_id,
                    "type": case_type,
                    "question": case["question"],
                    "expected_intent": expected,
                    "predicted_intent": predicted,
                }
            )

    return AccuracyReport(
        total=len(cases),
        correct=correct,
        accuracy=_rate(correct, len(cases)),
        by_type={
            case_type: AccuracyStats(
                total=total,
                correct=grouped_correct[case_type],
                accuracy=_rate(grouped_correct[case_type], total),
            )
            for case_type, total in grouped_totals.items()
        },
        confusion_matrix={expected: dict(counts) for expected, counts in confusion.items()},
        errors=errors,
    )


def _stats(counts: Counter[str]) -> IntentStats:
    total = sum(counts.values())
    return IntentStats(
        total=total,
        intent_counts=dict(counts),
        general_qa_rate=_rate(counts[GENERAL_QA], total),
    )


def _rate(part: int, whole: int) -> float:
    return part / whole if whole else 0.0


def print_report(report: Report, *, list_failures: bool = False) -> None:
    print(f"총 질문: {report.total}")
    print(f"GENERAL_QA 비율: {report.general_qa_rate * 100:.1f}%  (지시문 보강 없음)")
    print()

    print("intent 분포")
    for intent, count in sorted(report.intent_counts.items(), key=lambda kv: -kv[1]):
        print(f"  {intent:<20} {count:>4}  {_rate(count, report.total) * 100:>5.1f}%")
    print()

    if report.by_type:
        print("type별 GENERAL_QA 비율")
        for name, stats in sorted(report.by_type.items()):
            general_qa = stats.intent_counts.get(GENERAL_QA, 0)
            rate = stats.general_qa_rate * 100
            print(f"  {name:<10} {general_qa:>3}/{stats.total:<3} {rate:>6.1f}%")
        print()

    if list_failures and report.general_qa_cases:
        print("GENERAL_QA 로 떨어진 질문")
        for case in report.general_qa_cases:
            print(f"  [{case.get('id', '?')}] {case['question']}")


def print_accuracy_report(report: AccuracyReport, *, list_errors: bool = False) -> None:
    """정확도, 유형별 정확도, non-zero confusion과 선택적 오류 목록을 출력한다."""
    print(f"분류 정확도: {report.correct}/{report.total} ({report.accuracy * 100:.1f}%)")
    print()

    if report.by_type:
        print("type별 정확도")
        for name, stats in sorted(report.by_type.items()):
            print(
                f"  {name:<10} {stats.correct:>3}/{stats.total:<3} "
                f"{stats.accuracy * 100:>6.1f}%"
            )
        print()

    print("혼동 행렬 (expected -> predicted, 0건 생략)")
    for expected in INTENTS:
        for predicted in INTENTS:
            count = report.confusion_matrix.get(expected, {}).get(predicted, 0)
            if count:
                print(f"  {expected} -> {predicted}: {count}")
    print()

    if list_errors and report.errors:
        print("오분류 질문")
        for error in report.errors:
            print(
                f"  [{error['id']}] expected={error['expected_intent']} "
                f"predicted={error['predicted_intent']} type={error['type']}"
            )
            print(f"    {error['question']}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="의도 분류 커버리지를 측정한다.")
    parser.add_argument("paths", nargs="+", help="평가 jsonl 파일 경로")
    parser.add_argument("--list", action="store_true", help="GENERAL_QA 질문을 모두 출력")
    parser.add_argument("--gold", help="별도로 검토한 intent gold JSONL 경로")
    parser.add_argument("--list-errors", action="store_true", help="gold 대비 오분류 질문을 출력")
    args = parser.parse_args(argv)

    if args.list_errors and not args.gold:
        parser.error("--list-errors requires --gold")

    cases: list[dict[str, Any]] = []
    for path in args.paths:
        cases.extend(load_cases(path))

    print_report(summarize(cases), list_failures=args.list)
    if args.gold:
        print_accuracy_report(
            evaluate_accuracy(cases, load_gold_labels(args.gold)),
            list_errors=args.list_errors,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
