from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict
from pathlib import Path
from time import perf_counter
from typing import Any, Protocol

from qdrant_client.http.exceptions import ApiException

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.evaluate_local_judge import EvalCase, load_cases, source_recall

__all__ = ["load_cases", "run_export"]

SAFE_REPORT_ROOT = Path("reports/local-judge")


class AnswerCallable(Protocol):
    def __call__(self, question: str, *, top_k: int) -> Mapping[str, Any]: ...


def run_export(
    cases: Sequence[EvalCase],
    *,
    answer_model: str,
    top_k: int,
    output_dir: Path,
    run_id: str | None = None,
    search_method: str = "rrf",
    answer: AnswerCallable,
) -> Path:
    if top_k <= 0:
        raise ValueError("top_k must be greater than 0")
    if not cases:
        raise ValueError("at least one evaluation case is required")

    output = output_dir / _safe_run_id(run_id)
    output.mkdir(parents=True, exist_ok=False)
    records_path = output / "answers.jsonl"
    records_path.touch()
    _write_run_metadata(
        output / "run.json",
        cases=cases,
        run_id=output.name,
        answer_model=answer_model,
        top_k=top_k,
        search_method=search_method,
    )

    for case in cases:
        _append_jsonl(
            records_path,
            _export_case(case, top_k=top_k, answer=answer),
        )
    return output


def _export_case(
    case: EvalCase,
    *,
    top_k: int,
    answer: AnswerCallable,
) -> dict[str, Any]:
    started = perf_counter()
    case_data = {
        "id": case.id,
        "type": case.type,
        "question": case.question,
        "gold_answer": case.answer,
        "gold_jo": list(case.gold_jo),
    }
    try:
        result = answer(case.question, top_k=top_k)
        if not isinstance(result, Mapping):
            raise ValueError("answer response must be an object")
        candidate_answer = _required_text(result.get("answer"), "answer")
        sources = _sources(result.get("sources"))
    except (ApiException, OSError, RuntimeError, TypeError, ValueError) as exc:
        return {
            "status": "answer_error",
            "case": case_data,
            "answer_error": _error_text(exc),
            "elapsed_ms": _elapsed_ms(started),
        }

    source_ids = _source_ids(sources)
    return {
        "status": "answered",
        "case": case_data,
        "answer": candidate_answer,
        "source_ids": source_ids,
        "source_recall": source_recall(case.gold_jo, sources),
        "elapsed_ms": _elapsed_ms(started),
    }


def _write_run_metadata(
    path: Path,
    *,
    cases: Sequence[EvalCase],
    run_id: str,
    answer_model: str,
    top_k: int,
    search_method: str,
) -> None:
    serialized_cases = json.dumps(
        [asdict(case) for case in cases], ensure_ascii=False, sort_keys=True
    )
    metadata = {
        "run_id": run_id,
        "created_at": datetime.datetime.now(datetime.UTC).isoformat(),
        "answer_model": answer_model,
        "top_k": top_k,
        "search_method": search_method,
        "case_count": len(cases),
        "dataset_sha256": hashlib.sha256(serialized_cases.encode("utf-8")).hexdigest(),
    }
    path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _append_jsonl(path: Path, record: dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


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


def _elapsed_ms(started: float) -> int:
    return int((perf_counter() - started) * 1000)


def _error_text(exc: Exception) -> str:
    return f"{type(exc).__name__}: {exc}"


def _safe_run_id(run_id: str | None) -> str:
    if run_id is None:
        return datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    windows_path = Path(run_id)
    if (
        not run_id.strip()
        or run_id != run_id.strip()
        or run_id in {".", ".."}
        or "/" in run_id
        or "\\" in run_id
        or windows_path.is_absolute()
        or windows_path.drive
    ):
        raise ValueError("run_id must be a single safe directory name")
    return run_id


def main(
    argv: list[str] | None = None,
    *,
    load_cases_callable: Callable[[Path], list[EvalCase]] | None = None,
    settings_factory: Callable[[], Any] | None = None,
    answer_question_callable: Callable[..., Mapping[str, Any]] | None = None,
) -> int:
    parser = argparse.ArgumentParser(description="Export local RAG evaluation answers.")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--dataset", type=Path, default=Path("datasets/eval/qa_set.jsonl"))
    parser.add_argument("--output-dir", type=Path, default=SAFE_REPORT_ROOT)
    parser.add_argument("--run-id")
    parser.add_argument(
        "--search-method",
        choices=("dense", "rrf", "weighted_rrf", "dbsf", "rrf_reranker"),
        default="rrf",
    )
    parser.add_argument("--dense-weight", type=float, default=0.5)
    parser.add_argument("--sparse-weight", type=float, default=0.5)
    parser.add_argument("--reranker-device", default="cpu")
    parser.add_argument("--reranker-precision", choices=("fp32", "fp16"), default="fp32")
    parser.add_argument("--reranker-batch-size", type=int, default=8)
    parser.add_argument("--reranker-max-length", type=int, default=1024)
    args = parser.parse_args(argv)

    if args.top_k <= 0:
        parser.error("--top-k must be greater than 0")
    if not _is_safe_output_dir(args.output_dir):
        parser.error("--output-dir must be inside reports/local-judge")
    if not args.dataset.is_file():
        parser.error("--dataset must be an existing file")
    try:
        _safe_run_id(args.run_id)
    except ValueError as exc:
        parser.error(str(exc))

    if settings_factory is None or answer_question_callable is None:
        from app.config import Settings
        from app.rag_pipeline import answer_question

        settings_factory = settings_factory or Settings.from_env
        answer_question_callable = answer_question_callable or answer_question

    settings = settings_factory()
    retrieval_search = None
    if args.search_method != "rrf":
        from app.rag_search_methods import create_rag_search
        from app.reranker import RerankerConfig
        from app.retrieval_search import FusionWeights

        retrieval_search = create_rag_search(
            args.search_method,
            weights=FusionWeights(args.dense_weight, args.sparse_weight),
            reranker_config=RerankerConfig(
                device=args.reranker_device,
                precision=args.reranker_precision,
                batch_size=args.reranker_batch_size,
                max_length=args.reranker_max_length,
            ),
        )
    output = run_export(
        (load_cases_callable or load_cases)(args.dataset),
        answer_model=settings.llm_model,
        top_k=args.top_k,
        output_dir=args.output_dir,
        run_id=args.run_id,
        search_method=args.search_method,
        answer=lambda question, *, top_k: answer_question_callable(
            question,
            top_k=top_k,
            settings=settings,
            **({"retrieval_search": retrieval_search} if retrieval_search is not None else {}),
        ),
    )
    print(f"RAG answer export written to {output}")
    records = _read_jsonl(output / "answers.jsonl")
    return 0 if any(record.get("status") == "answered" for record in records) else 1


def _is_safe_output_dir(path: Path) -> bool:
    try:
        path.resolve().relative_to(SAFE_REPORT_ROOT.resolve())
    except ValueError:
        return False
    return True


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


if __name__ == "__main__":
    raise SystemExit(main())
