from __future__ import annotations

import argparse
import datetime
import sys
from pathlib import Path
from statistics import fmean
from time import perf_counter

from qdrant_client import QdrantClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import Settings
from app.embeddings import embed_text
from app.question_interpreter import interpret_question
from app.reranker import (
    RerankerConfig,
    TransformersRerankerBackend,
    rerank_hits,
)
from app.retrieval_evaluation import (
    QueryRepresentation,
    RetrievalCase,
    RetrievalOutcome,
    evaluate_quality,
)
from app.retrieval_reports import (
    append_result,
    create_run_directory,
    render_summary,
    write_run_metadata,
)
from app.retrieval_run_metadata import collect_run_metadata
from app.retrieval_search import FusionWeights, SearchMethod, SearchRequest, search
from app.sparse import text_to_sparse
from scripts.evaluate_local_judge import load_cases

SAFE_REPORT_ROOT = Path("reports/retrieval-eval")
RERANK_METHOD = "rrf_reranker"
DEFAULT_METHODS = "dense,bm25,rrf,weighted_rrf,dbsf"


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    _validate_args(parser, args)

    settings = Settings.from_env()
    cases = tuple(
        RetrievalCase(case.id, case.question, case.gold_jo) for case in load_cases(args.dataset)
    )
    methods = tuple(value.strip() for value in args.methods.split(",") if value.strip())
    output = create_run_directory(args.output_dir, args.run_id or _default_run_id())
    client = QdrantClient(url=settings.qdrant_url)
    reranker_config = RerankerConfig(
        device=args.reranker_device,
        precision=args.reranker_precision,
        batch_size=args.reranker_batch_size,
        max_length=args.reranker_max_length,
    )
    reranker = TransformersRerankerBackend(reranker_config) if RERANK_METHOD in methods else None
    weights = FusionWeights(args.dense_weight, args.sparse_weight)
    represent = _representation_builder(settings)
    retrieve = _retriever(
        client,
        settings=settings,
        candidate_limit=args.candidate_limit,
        rerank_candidate_limit=args.rerank_candidate_limit,
        weights=weights,
        reranker=reranker,
        reranker_config=reranker_config,
        repetitions=args.latency_repetitions,
    )

    warm_representation = represent(cases[0].question)
    for method in methods:
        retrieve(method, warm_representation)

    write_run_metadata(
        output / "run.json",
        collect_run_metadata(
            run_id=output.name,
            split=args.split,
            dataset_path=args.dataset,
            document_path=Path("datasets/docs/regulations.md"),
            settings=settings,
            methods=methods,
            case_count=len(cases),
            top_k=args.top_k,
            candidate_limit=args.candidate_limit,
            rerank_candidate_limit=args.rerank_candidate_limit,
            weights=weights,
            reranker_config=reranker_config if reranker else None,
            reranker_cold_start_ms=reranker.cold_start_ms if reranker else None,
            latency_repetitions=args.latency_repetitions,
            seed=args.seed,
        ),
    )
    records = evaluate_quality(
        cases,
        methods=methods,
        top_k=args.top_k,
        represent=represent,
        retrieve=retrieve,
        record_sink=lambda record: append_result(output / "results.jsonl", record),
        seed=args.seed,
    )
    (output / "summary.md").write_text(
        render_summary(records, seed=args.seed),
        encoding="utf-8",
    )
    print(f"Retrieval evaluation written to {output}")
    return 0 if any(record.status == "success" for record in records) else 1


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Evaluate local policy retrieval methods.")
    parser.add_argument("--dataset", type=Path, default=Path("datasets/eval/qa_set.jsonl"))
    parser.add_argument("--split", choices=("development", "holdout"), required=True)
    parser.add_argument("--methods", default=DEFAULT_METHODS)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--candidate-limit", type=int, default=20)
    parser.add_argument("--rerank-candidate-limit", type=int, default=40)
    parser.add_argument("--run-id")
    parser.add_argument("--output-dir", type=Path, default=SAFE_REPORT_ROOT)
    parser.add_argument("--seed", type=int, default=20260831)
    parser.add_argument("--latency-repetitions", type=int, default=3)
    parser.add_argument("--dense-weight", type=float, default=0.5)
    parser.add_argument("--sparse-weight", type=float, default=0.5)
    parser.add_argument("--reranker-device", default="cpu")
    parser.add_argument("--reranker-precision", choices=("fp32", "fp16"), default="fp32")
    parser.add_argument("--reranker-batch-size", type=int, default=8)
    parser.add_argument("--reranker-max-length", type=int, default=1024)
    return parser


def _validate_args(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    if not _is_safe_output_dir(args.output_dir):
        parser.error("--output-dir must be inside reports/retrieval-eval")
    if not args.dataset.is_file():
        parser.error("--dataset must be an existing file")
    for name in ("top_k", "candidate_limit", "rerank_candidate_limit", "latency_repetitions"):
        if getattr(args, name) <= 0:
            parser.error(f"--{name.replace('_', '-')} must be greater than 0")
    valid = {method.value for method in SearchMethod} | {RERANK_METHOD}
    requested = {value.strip() for value in args.methods.split(",") if value.strip()}
    if not requested or requested - valid:
        parser.error(f"--methods must contain only: {', '.join(sorted(valid))}")


def _representation_builder(settings: Settings):
    def build(question: str) -> QueryRepresentation:
        retrieval_question = interpret_question(question).retrieval_question
        started = perf_counter()
        dense = tuple(
            embed_text(
                settings.ollama_base_url,
                settings.embedding_model,
                retrieval_question,
            )
        )
        dense_ms = (perf_counter() - started) * 1000
        started = perf_counter()
        sparse = text_to_sparse(retrieval_question)
        sparse_ms = (perf_counter() - started) * 1000
        return QueryRepresentation(
            retrieval_question,
            dense,
            tuple(sparse["indices"]),
            tuple(sparse["values"]),
            dense_ms,
            sparse_ms,
        )

    return build


def _retriever(
    client: QdrantClient,
    *,
    settings: Settings,
    candidate_limit: int,
    rerank_candidate_limit: int,
    weights: FusionWeights,
    reranker: TransformersRerankerBackend | None,
    reranker_config: RerankerConfig,
    repetitions: int,
):
    def retrieve(method: str, representation: QueryRepresentation) -> RetrievalOutcome:
        search_method = SearchMethod.RRF if method == RERANK_METHOD else SearchMethod(method)
        limit = rerank_candidate_limit if method == RERANK_METHOD else candidate_limit
        request = SearchRequest(
            collection_name=settings.qdrant_collection,
            method=search_method,
            dense_vector=representation.dense_vector,
            sparse_indices=representation.sparse_indices,
            sparse_values=representation.sparse_values,
            candidate_limit=limit,
            weights=weights if search_method is SearchMethod.WEIGHTED_RRF else None,
        )
        search_times: list[float] = []
        rerank_times: list[float] = []
        final_hits = ()
        for _ in range(repetitions):
            started = perf_counter()
            final_hits = search(client, request)
            search_times.append((perf_counter() - started) * 1000)
            if method == RERANK_METHOD:
                if reranker is None:
                    raise RuntimeError("reranker method requires the optional backend")
                result = rerank_hits(
                    representation.retrieval_question,
                    final_hits,
                    backend=reranker,
                    config=reranker_config,
                )
                final_hits = result.hits
                rerank_times.append(result.elapsed_ms)
        return RetrievalOutcome(
            final_hits,
            fmean(search_times),
            fmean(rerank_times) if rerank_times else 0.0,
        )

    return retrieve


def _default_run_id() -> str:
    return datetime.datetime.now().strftime("%Y%m%d-%H%M%S")


def _is_safe_output_dir(path: Path) -> bool:
    try:
        path.resolve().relative_to(SAFE_REPORT_ROOT.resolve())
    except ValueError:
        return False
    return True


if __name__ == "__main__":
    raise SystemExit(main())
