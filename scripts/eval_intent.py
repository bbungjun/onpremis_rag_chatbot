"""의도 분류 커버리지 측정.

`app.question_interpreter`는 마커 문자열 포함 검사로 intent 를 정한다. 마커에 걸리지
않으면 GENERAL_QA 가 되고, 그 경우 canonical_question 에 답변 지시문이 붙지 않는다.
즉 GENERAL_QA 비율이 곧 "지시문 보강을 못 받는 질문의 비율"이다.

검색에는 영향이 없다(retrieval_question 은 그대로 나간다). 그래서 이 수치는
검색 품질이 아니라 답변 지시 커버리지를 재는 것이다.

사용:
    python scripts/eval_intent.py datasets/eval/qa_set.jsonl
    python scripts/eval_intent.py datasets/eval/*.jsonl --list
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

from app.question_interpreter import GENERAL_QA, interpret_question  # noqa: E402


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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="의도 분류 커버리지를 측정한다.")
    parser.add_argument("paths", nargs="+", help="평가 jsonl 파일 경로")
    parser.add_argument("--list", action="store_true", help="GENERAL_QA 질문을 모두 출력")
    args = parser.parse_args(argv)

    cases: list[dict[str, Any]] = []
    for path in args.paths:
        cases.extend(load_cases(path))

    print_report(summarize(cases), list_failures=args.list)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
