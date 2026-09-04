from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from random import Random

from app.retrieval_metrics import RankingMetrics, ranking_metrics
from app.retrieval_search import SearchHit, collapse_parent_hits


@dataclass(frozen=True, slots=True)
class RetrievalCase:
    id: str
    question: str
    gold_parent_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class QueryRepresentation:
    retrieval_question: str
    dense_vector: tuple[float, ...]
    sparse_indices: tuple[int, ...]
    sparse_values: tuple[float, ...]
    dense_embedding_ms: float
    sparse_encoding_ms: float


@dataclass(frozen=True, slots=True)
class RetrievalOutcome:
    hits: tuple[SearchHit, ...]
    qdrant_search_ms: float
    reranker_ms: float = 0.0


@dataclass(frozen=True, slots=True)
class EvaluationRecord:
    case_id: str
    method: str
    status: str
    gold_parent_ids: tuple[str, ...]
    predicted_parent_ids: tuple[str, ...]
    predicted_child_ids: tuple[str, ...]
    metrics: RankingMetrics | None
    timing_ms: dict[str, float]
    candidate_recall: float | None = None
    error: str | None = None


RepresentCallable = Callable[[str], QueryRepresentation]
RetrieveCallable = Callable[[str, QueryRepresentation], RetrievalOutcome]
RecordSink = Callable[[EvaluationRecord], object]


def evaluate_quality(
    cases: Sequence[RetrievalCase],
    *,
    methods: Sequence[str],
    top_k: int,
    represent: RepresentCallable,
    retrieve: RetrieveCallable,
    record_sink: RecordSink | None = None,
    seed: int | None = None,
) -> tuple[EvaluationRecord, ...]:
    if not cases:
        raise ValueError("at least one retrieval case is required")
    if not methods:
        raise ValueError("at least one retrieval method is required")
    if top_k <= 0:
        raise ValueError("top_k must be greater than 0")

    records: list[EvaluationRecord] = []
    random = Random(seed)
    for case in cases:
        representation = represent(case.question)
        ordered_methods = list(methods)
        if seed is not None:
            random.shuffle(ordered_methods)
        for method in ordered_methods:
            record = _evaluate_method(
                case,
                method=method,
                representation=representation,
                top_k=top_k,
                retrieve=retrieve,
            )
            records.append(record)
            if record_sink is not None:
                record_sink(record)
    return tuple(records)


def _evaluate_method(
    case: RetrievalCase,
    *,
    method: str,
    representation: QueryRepresentation,
    top_k: int,
    retrieve: RetrieveCallable,
) -> EvaluationRecord:
    base_timing = {
        "dense_embedding": representation.dense_embedding_ms,
        "sparse_encoding": representation.sparse_encoding_ms,
    }
    try:
        outcome = retrieve(method, representation)
        parents = collapse_parent_hits(outcome.hits, top_k)
        predicted_parents = tuple(parent.parent_id for parent in parents)
        predicted_children = tuple(hit.payload.get("chunk_id", "") for hit in outcome.hits)
        child_ids = tuple(value for value in predicted_children if isinstance(value, str))
        metrics = ranking_metrics(case.gold_parent_ids, predicted_parents)
        candidate_recall = _candidate_recall(case.gold_parent_ids, outcome.hits)
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        return EvaluationRecord(
            case_id=case.id,
            method=method,
            status="error",
            gold_parent_ids=case.gold_parent_ids,
            predicted_parent_ids=(),
            predicted_child_ids=(),
            metrics=None,
            timing_ms=base_timing,
            error=f"{type(exc).__name__}: {exc}",
        )

    return EvaluationRecord(
        case_id=case.id,
        method=method,
        status="success",
        gold_parent_ids=case.gold_parent_ids,
        predicted_parent_ids=predicted_parents,
        predicted_child_ids=child_ids,
        metrics=metrics,
        candidate_recall=candidate_recall,
        timing_ms={
            **base_timing,
            "qdrant_search": outcome.qdrant_search_ms,
            "reranker": outcome.reranker_ms,
            "retrieval_total": (
                representation.dense_embedding_ms
                + representation.sparse_encoding_ms
                + outcome.qdrant_search_ms
                + outcome.reranker_ms
            ),
        },
    )


def _candidate_recall(gold_parent_ids: Sequence[str], hits: Sequence[SearchHit]) -> float:
    candidate_parents = {
        parent_id for hit in hits if isinstance((parent_id := hit.payload.get("parent_id")), str)
    }
    return len(set(gold_parent_ids) & candidate_parents) / len(set(gold_parent_ids))
