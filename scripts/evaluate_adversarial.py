"""무답·공격 질문 평가 실행기.

실행 모드: 데이터셋의 각 질문을 실제 RAG 파이프라인으로 답하고 answers.jsonl 로 즉시 flush 한 뒤
결정적 지표를 계산한다.
채점 모드(--answers-file): 이미 export 된 answers.jsonl 만 다시 채점한다. LLM 을 호출하지 않는다.
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
import sys
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from time import perf_counter
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.adversarial_eval import (
    AdversarialCase,
    case_to_dict,
    load_adversarial_cases,
    load_parent_texts,
    render_summary_markdown,
    score_record,
    summarize,
)

SAFE_REPORT_ROOT = Path("reports/adversarial-eval")
DEFAULT_DOCS = (
    Path("datasets/docs/regulations.md"),
    Path("datasets/eval/adversarial_docs/injected_regulations.md"),
)
AnswerCallable = Callable[..., Mapping[str, Any]]


def run_answers(
    cases: Sequence[AdversarialCase],
    *,
    answer: AnswerCallable,
    top_k: int,
    output_dir: Path,
    run_id: str,
    metadata: Mapping[str, Any],
) -> Path:
    if top_k <= 0:
        raise ValueError("top_k must be greater than 0")
    if not cases:
        raise ValueError("at least one case is required")
    output = output_dir / _safe_run_id(run_id)
    output.mkdir(parents=True, exist_ok=False)
    answers_path = output / "answers.jsonl"
    answers_path.touch()

    serialized = json.dumps(
        [case_to_dict(case) for case in cases], ensure_ascii=False, sort_keys=True
    )
    run = {
        **metadata,
        "run_id": output.name,
        "created_at": datetime.datetime.now(datetime.UTC).isoformat(),
        "top_k": top_k,
        "case_count": len(cases),
        "dataset_sha256": hashlib.sha256(serialized.encode("utf-8")).hexdigest(),
    }
    (output / "run.json").write_text(
        json.dumps(run, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    for index, case in enumerate(cases, start=1):
        print(f"[{index}/{len(cases)}] {case.id} ({case.label})", flush=True)
        _append_jsonl(answers_path, _answer_case(case, answer=answer, top_k=top_k))
    return output


def _answer_case(case: AdversarialCase, *, answer: AnswerCallable, top_k: int) -> dict[str, Any]:
    started = perf_counter()
    base = {"case": case_to_dict(case)}
    try:
        result = answer(case.question, top_k=top_k)
        text = result.get("answer") if isinstance(result, Mapping) else None
        sources = result.get("sources") if isinstance(result, Mapping) else None
        if not isinstance(text, str) or not text.strip():
            raise ValueError("answer must be a non-empty string")
        if not isinstance(sources, list):
            raise ValueError("sources must be a list")
    except Exception as exc:  # noqa: BLE001 - 실행 중 어떤 오류도 기록하고 계속 진행한다.
        return {
            **base,
            "status": "answer_error",
            "answer_error": f"{type(exc).__name__}: {exc}",
            "elapsed_ms": _elapsed_ms(started),
        }
    return {
        **base,
        "status": "answered",
        "answer": text.strip(),
        "source_ids": [
            source["chunk_id"]
            for source in sources
            if isinstance(source, Mapping) and isinstance(source.get("chunk_id"), str)
        ],
        "elapsed_ms": _elapsed_ms(started),
    }


def score_run(output: Path, doc_paths: Sequence[Path]) -> dict[str, Any]:
    records = _read_jsonl(output / "answers.jsonl")
    if not records:
        raise ValueError(f"{output / 'answers.jsonl'} is empty")
    run = json.loads((output / "run.json").read_text(encoding="utf-8"))
    parent_texts = load_parent_texts(doc_paths)
    scored = [score_record(record, parent_texts) for record in records]
    summary = summarize(scored)
    summary["scored_at"] = datetime.datetime.now(datetime.UTC).isoformat()
    summary["docs_sha256"] = {str(path): _sha256(path) for path in doc_paths}
    (output / "scores.jsonl").write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in scored), encoding="utf-8"
    )
    (output / "metrics.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (output / "summary.md").write_text(render_summary_markdown(summary, run), encoding="utf-8")
    return summary


def main(
    argv: list[str] | None = None,
    *,
    settings_factory: Callable[[], Any] | None = None,
    answer_question_callable: AnswerCallable | None = None,
) -> int:
    parser = argparse.ArgumentParser(description="Evaluate refusal and prompt-injection behaviour.")
    parser.add_argument(
        "--dataset", type=Path, default=Path("datasets/eval/qa_adversarial_dev.jsonl")
    )
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--output-dir", type=Path, default=SAFE_REPORT_ROOT)
    parser.add_argument("--run-id")
    parser.add_argument(
        "--answers-file",
        type=Path,
        help="이미 export 된 answers.jsonl 을 다시 채점만 한다 (LLM 호출 없음)",
    )
    parser.add_argument(
        "--docs",
        type=Path,
        nargs="+",
        default=list(DEFAULT_DOCS),
        help="출처 날조 판정에 쓸 코퍼스 문서",
    )
    args = parser.parse_args(argv)

    if args.top_k <= 0:
        parser.error("--top-k must be greater than 0")
    if not _is_inside(args.output_dir, SAFE_REPORT_ROOT):
        parser.error("--output-dir must be inside reports/adversarial-eval")
    missing = [str(path) for path in args.docs if not path.is_file()]
    if missing:
        parser.error(f"--docs not found: {', '.join(missing)}")

    if args.answers_file is not None:
        if not args.answers_file.is_file():
            parser.error("--answers-file must be an existing file")
        summary = score_run(args.answers_file.parent, args.docs)
        print(f"Scored {args.answers_file.parent}")
        _print_metrics(summary)
        return 0 if summary["metrics"]["answer_errors"] == 0 else 1

    if not args.dataset.is_file():
        parser.error("--dataset must be an existing file")
    try:
        run_id = _safe_run_id(args.run_id)
    except ValueError as exc:
        parser.error(str(exc))

    if settings_factory is None or answer_question_callable is None:
        from app.config import Settings
        from app.rag_pipeline import answer_question

        settings_factory = settings_factory or Settings.from_env
        answer_question_callable = answer_question_callable or answer_question

    settings = settings_factory()
    cases = load_adversarial_cases(args.dataset)
    output = run_answers(
        cases,
        answer=lambda question, *, top_k: answer_question_callable(
            question, top_k=top_k, settings=settings
        ),
        top_k=args.top_k,
        output_dir=args.output_dir,
        run_id=run_id,
        metadata={
            "answer_model": settings.llm_model,
            "embedding_model": settings.embedding_model,
            "qdrant_collection": settings.qdrant_collection,
            "num_ctx": settings.num_ctx,
            "num_predict": settings.num_predict,
            "temperature": settings.temperature,
            "dataset_path": str(args.dataset),
            "search_method": "rrf",
        },
    )
    summary = score_run(output, args.docs)
    print(f"Adversarial evaluation written to {output}")
    _print_metrics(summary)
    return 0 if summary["metrics"]["answer_errors"] == 0 else 1


def _print_metrics(summary: Mapping[str, Any]) -> None:
    for name, value in summary["metrics"].items():
        print(f"  {name}: {value}")
    print(f"  all_targets_met: {summary['all_targets_met']}")


def _safe_run_id(run_id: str | None) -> str:
    if run_id is None:
        return datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    candidate = Path(run_id)
    if (
        not run_id.strip()
        or run_id != run_id.strip()
        or run_id in {".", ".."}
        or "/" in run_id
        or "\\" in run_id
        or candidate.is_absolute()
        or candidate.drive
    ):
        raise ValueError("run_id must be a single safe directory name")
    return run_id


def _is_inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


def _append_jsonl(path: Path, record: Mapping[str, Any]) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _elapsed_ms(started: float) -> int:
    return int((perf_counter() - started) * 1000)


if __name__ == "__main__":
    raise SystemExit(main())
