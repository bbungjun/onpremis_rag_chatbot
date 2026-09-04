from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
import sys
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from statistics import fmean
from time import perf_counter
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.local_judge import JudgeVerdict, judge_answer, validate_judge_model

SAFE_REPORT_ROOT = Path("reports/local-judge")


@dataclass(frozen=True)
class EvalCase:
    id: str
    type: str
    question: str
    gold_jo: tuple[str, ...]
    answer: str


AnswerCallable = Callable[..., dict[str, Any]]
JudgeCallable = Callable[..., JudgeVerdict]


def load_cases(path: Path) -> list[EvalCase]:
    rows = path.read_text(encoding="utf-8").splitlines()
    if not rows:
        raise ValueError("evaluation file must not be empty")

    cases: list[EvalCase] = []
    seen_ids: set[str] = set()
    for line_number, line in enumerate(rows, start=1):
        if not line.strip():
            raise ValueError(f"evaluation file has a blank line at {line_number}")
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"evaluation file has invalid JSON at line {line_number}") from exc
        if not isinstance(row, dict):
            raise ValueError(f"evaluation row {line_number} must be an object")

        case = _parse_case(row, line_number)
        if case.id in seen_ids:
            raise ValueError(f"evaluation file has duplicate case id {case.id!r}")
        seen_ids.add(case.id)
        cases.append(case)
    return cases


def source_recall(gold_jo: Sequence[str], sources: Sequence[dict[str, Any]]) -> float:
    expected = set(gold_jo)
    if not expected:
        return 1.0
    returned = {
        _normalized_source_id(source.get("chunk_id"))
        for source in sources
        if isinstance(source, dict)
    }
    return len(expected & returned) / len(expected)


def answer_from_export(path: Path) -> AnswerCallable:
    records = _read_jsonl(path)
    by_question: dict[str, dict[str, Any]] = {}
    for record in records:
        if record.get("status") != "answered":
            continue
        case = record.get("case")
        if not isinstance(case, dict) or not isinstance(case.get("question"), str):
            raise ValueError("exported answer record is missing its question")
        source_ids = record.get("source_ids")
        if not isinstance(source_ids, list):
            raise ValueError("exported answer record is missing source_ids")
        by_question[case["question"]] = {
            "answer": record.get("answer"),
            "sources": [{"chunk_id": source_id} for source_id in source_ids],
        }

    def answer(question: str, *, top_k: int) -> dict[str, Any]:
        del top_k
        try:
            return by_question[question]
        except KeyError as exc:
            raise ValueError(f"export has no answered record for question: {question}") from exc

    return answer


def run_evaluation(
    cases: Sequence[EvalCase],
    *,
    answer_model: str,
    judge_model: str,
    base_url: str,
    num_ctx: int,
    output_dir: Path,
    run_id: str | None = None,
    top_k: int = 5,
    search_method: str = "rrf",
    answer: AnswerCallable,
    judge: JudgeCallable = judge_answer,
) -> Path:
    judge_model = validate_judge_model(judge_model)
    if top_k <= 0:
        raise ValueError("top_k must be greater than 0")
    if not cases:
        raise ValueError("at least one evaluation case is required")

    output = output_dir / _safe_run_id(run_id)
    output.mkdir(parents=True, exist_ok=False)
    result_path = output / "results.jsonl"
    result_path.touch()
    _write_run_metadata(
        output / "run.json",
        cases=cases,
        run_id=output.name,
        answer_model=answer_model,
        judge_model=judge_model,
        num_ctx=num_ctx,
        top_k=top_k,
        search_method=search_method,
    )

    records: list[dict[str, Any]] = []
    try:
        for case in cases:
            record = _evaluate_case(
                case,
                answer_model=answer_model,
                judge_model=judge_model,
                base_url=base_url,
                num_ctx=num_ctx,
                top_k=top_k,
                answer=answer,
                judge=judge,
            )
            _append_jsonl(result_path, record)
            records.append(record)
    finally:
        (output / "summary.md").write_text(
            render_summary(summarize_records(records)), encoding="utf-8"
        )
    return output


def summarize_records(records: Sequence[dict[str, Any]]) -> dict[str, Any]:
    judged = [record for record in records if record.get("status") == "judged"]
    answered = [record for record in records if record.get("status") in {"judged", "judge_error"}]
    answer_errors = [record for record in records if record.get("status") == "answer_error"]
    judge_errors = [record for record in records if record.get("status") == "judge_error"]

    def mean_verdict_score(name: str) -> float | None:
        if not judged:
            return None
        return fmean(float(record["verdict"][name]) for record in judged)

    lowest = sorted(judged, key=lambda record: int(record["verdict"]["total"]))[:5]
    return {
        "answered_count": len(answered),
        "judged_count": len(judged),
        "answer_error_count": len(answer_errors),
        "judge_error_count": len(judge_errors),
        "mean_total": mean_verdict_score("total"),
        "mean_correctness": mean_verdict_score("correctness"),
        "mean_groundedness": mean_verdict_score("groundedness"),
        "mean_completeness": mean_verdict_score("completeness"),
        "mean_source_recall": (
            fmean(float(record["source_recall"]) for record in answered) if answered else None
        ),
        "lowest_cases": [
            {
                "id": record["case"]["id"],
                "total": record["verdict"]["total"],
                "rationale": record["verdict"]["rationale"],
            }
            for record in lowest
        ],
        "judge_errors": [
            {
                "id": record["case"]["id"],
                "error": record["judge_error"],
            }
            for record in judge_errors[:5]
        ],
        "answer_errors": [
            {
                "id": record["case"]["id"],
                "error": record["answer_error"],
            }
            for record in answer_errors[:5]
        ],
    }


def render_summary(summary: dict[str, Any]) -> str:
    lines = [
        "# Local LLM Judge Evaluation",
        "",
        f"- Answered cases: {summary['answered_count']}",
        f"- Judged cases: {summary['judged_count']}",
        f"- Answer errors: {summary['answer_error_count']}",
        f"- Judge errors: {summary['judge_error_count']}",
    ]
    if summary["judged_count"]:
        lines.extend(
            [
                f"- Mean Judge total: {summary['mean_total']:.2f} / 6",
                f"- Mean correctness: {summary['mean_correctness']:.2f} / 2",
                f"- Mean groundedness: {summary['mean_groundedness']:.2f} / 2",
                f"- Mean completeness: {summary['mean_completeness']:.2f} / 2",
            ]
        )
    if summary["mean_source_recall"] is not None:
        lines.append(f"- Mean source recall: {summary['mean_source_recall']:.3f}")
    if summary["lowest_cases"]:
        lines.extend(["", "## Lowest-scoring cases"])
        lines.extend(
            "- {id}: {total} / 6 - {rationale}".format(
                id=case["id"],
                total=case["total"],
                rationale=_markdown_inline(case["rationale"]),
            )
            for case in summary["lowest_cases"]
        )
    if summary["judge_errors"]:
        lines.extend(["", "## Judge errors"])
        lines.extend(
            f"- {error['id']}: {_markdown_inline(error['error'])}"
            for error in summary["judge_errors"]
        )
    if summary["answer_errors"]:
        lines.extend(["", "## Answer errors"])
        lines.extend(
            f"- {error['id']}: {_markdown_inline(error['error'])}"
            for error in summary["answer_errors"]
        )
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Evaluate RAG answers with a separate local LLM Judge."
    )
    parser.add_argument("--judge-model", required=True)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--dataset", type=Path, default=Path("datasets/eval/qa_set.jsonl"))
    parser.add_argument(
        "--search-method",
        choices=("dense", "rrf", "weighted_rrf", "dbsf", "rrf_reranker"),
        default="rrf",
    )
    parser.add_argument("--output-dir", type=Path, default=SAFE_REPORT_ROOT)
    parser.add_argument("--answers-file", type=Path)
    parser.add_argument("--run-id")
    args = parser.parse_args(argv)

    try:
        validate_judge_model(args.judge_model)
    except ValueError as exc:
        parser.error(str(exc))
    if args.limit is not None and args.limit <= 0:
        parser.error("--limit must be greater than 0")
    if not _is_safe_output_dir(args.output_dir):
        parser.error("--output-dir must be inside reports/local-judge")
    if not args.dataset.is_file():
        parser.error("--dataset must be an existing file")
    if args.answers_file is not None and not args.answers_file.is_file():
        parser.error("--answers-file must be an existing JSONL file")

    from app.config import Settings
    from app.rag_pipeline import answer_question

    settings = Settings.from_env()
    cases = load_cases(args.dataset)
    if args.limit is not None:
        cases = cases[: args.limit]
    retrieval_search = None
    if args.answers_file is None and args.search_method != "rrf":
        from app.rag_search_methods import create_rag_search

        retrieval_search = create_rag_search(args.search_method)
    if args.answers_file is not None:
        answer_callable = answer_from_export(args.answers_file)
    else:

        def answer_callable(question: str, *, top_k: int) -> dict[str, Any]:
            return answer_question(
                question,
                top_k=top_k,
                settings=settings,
                **({"retrieval_search": retrieval_search} if retrieval_search is not None else {}),
            )

    output = run_evaluation(
        cases,
        answer_model=settings.llm_model,
        judge_model=args.judge_model,
        base_url=settings.ollama_base_url,
        num_ctx=settings.num_ctx,
        output_dir=args.output_dir,
        run_id=args.run_id,
        top_k=args.top_k,
        search_method=args.search_method,
        answer=answer_callable,
    )
    records = _read_jsonl(output / "results.jsonl")
    judged_count = sum(record.get("status") == "judged" for record in records)
    print(f"Local Judge report written to {output}")
    return 0 if judged_count else 1


def _evaluate_case(
    case: EvalCase,
    *,
    answer_model: str,
    judge_model: str,
    base_url: str,
    num_ctx: int,
    top_k: int,
    answer: AnswerCallable,
    judge: JudgeCallable,
) -> dict[str, Any]:
    started = perf_counter()
    models = {"answer": answer_model, "judge": judge_model}
    try:
        result = answer(case.question, top_k=top_k)
        candidate_answer = _required_text(result.get("answer"), "answer")
        sources = _sources(result.get("sources"))
    except Exception as exc:
        return {
            "status": "answer_error",
            "case": {"id": case.id, "type": case.type},
            "models": models,
            "answer_error": _error_text(exc),
            "elapsed_ms": _elapsed_ms(started),
        }

    returned_source_ids = _source_ids(sources)
    record = {
        "case": {"id": case.id, "type": case.type},
        "models": models,
        "answer": candidate_answer,
        "source_ids": returned_source_ids,
        "source_recall": source_recall(case.gold_jo, sources),
    }
    try:
        verdict = judge(
            base_url=base_url,
            judge_model=judge_model,
            question=case.question,
            reference_answer=case.answer,
            candidate_answer=candidate_answer,
            source_ids=returned_source_ids,
            num_ctx=num_ctx,
        )
    except Exception as exc:
        return {
            **record,
            "status": "judge_error",
            "judge_error": _error_text(exc),
            "elapsed_ms": _elapsed_ms(started),
        }
    return {
        **record,
        "status": "judged",
        "verdict": {**asdict(verdict), "total": verdict.total},
        "elapsed_ms": _elapsed_ms(started),
    }


def _parse_case(row: dict[str, Any], line_number: int) -> EvalCase:
    required_fields = {"id", "type", "question", "gold_jo", "answer"}
    if set(row) != required_fields:
        raise ValueError(
            f"evaluation row {line_number} must contain exactly {sorted(required_fields)}"
        )
    case_id = _required_text(row["id"], "id")
    case_type = _required_text(row["type"], "type")
    question = _required_text(row["question"], "question")
    answer = _required_text(row["answer"], "answer")
    gold = row["gold_jo"]
    if not isinstance(gold, list) or not gold:
        raise ValueError(f"evaluation row {line_number} gold_jo must be a non-empty list")
    gold_jo = tuple(_required_text(value, "gold_jo") for value in gold)
    if len(set(gold_jo)) != len(gold_jo):
        raise ValueError(f"evaluation row {line_number} gold_jo must not contain duplicates")
    return EvalCase(case_id, case_type, question, gold_jo, answer)


def _required_text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value.strip()


def _sources(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise ValueError("sources must be a list")
    if not all(isinstance(source, dict) for source in value):
        raise ValueError("sources must contain objects")
    return value


def _source_ids(sources: Sequence[dict[str, Any]]) -> list[str]:
    return [
        source_id
        for source in sources
        if (source_id := source.get("chunk_id")) and isinstance(source_id, str)
    ]


def _normalized_source_id(value: Any) -> str:
    return value.rsplit("::", 1)[-1] if isinstance(value, str) else ""


def _write_run_metadata(
    path: Path,
    *,
    cases: Sequence[EvalCase],
    run_id: str,
    answer_model: str,
    judge_model: str,
    num_ctx: int,
    top_k: int,
    search_method: str,
) -> None:
    serialized_cases = json.dumps(
        [asdict(case) for case in cases], ensure_ascii=False, sort_keys=True
    )
    metadata = {
        "run_id": run_id,
        "created_at": datetime.datetime.now(datetime.UTC).isoformat(),
        "dataset": {
            "case_count": len(cases),
            "sha256": hashlib.sha256(serialized_cases.encode("utf-8")).hexdigest(),
        },
        "models": {"answer": answer_model, "judge": judge_model},
        "settings": {"num_ctx": num_ctx, "top_k": top_k},
        "search_method": search_method,
    }
    path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _append_jsonl(path: Path, record: dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def _elapsed_ms(started: float) -> int:
    return int((perf_counter() - started) * 1000)


def _error_text(exc: Exception) -> str:
    return f"{type(exc).__name__}: {exc}"


def _markdown_inline(value: str) -> str:
    normalized = " ".join(value.split())
    return (
        normalized.replace("\\", "\\\\")
        .replace("&", "\\&")
        .replace("<", "\\<")
        .replace(">", "\\>")
        .replace("[", "\\[")
        .replace("]", "\\]")
    )


def _is_safe_output_dir(path: Path) -> bool:
    try:
        path.resolve().relative_to(SAFE_REPORT_ROOT.resolve())
    except ValueError:
        return False
    return True


def _safe_run_id(run_id: str | None) -> str:
    if run_id is None:
        return datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    if (
        not run_id.strip()
        or run_id != run_id.strip()
        or run_id in {".", ".."}
        or "/" in run_id
        or "\\" in run_id
        or Path(run_id).is_absolute()
        or Path(run_id).drive
    ):
        raise ValueError("run_id must be a single safe directory name")
    return run_id


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


if __name__ == "__main__":
    raise SystemExit(main())
