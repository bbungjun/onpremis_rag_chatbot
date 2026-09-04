from __future__ import annotations

from collections.abc import Callable

from qdrant_client import QdrantClient, models

from app.config import Settings
from app.reranker import (
    RerankerConfig,
    TransformersRerankerBackend,
    rerank_hits,
)
from app.retrieval_search import FusionWeights, SearchMethod, SearchRequest, search

RERANK_METHOD = "rrf_reranker"


def create_rag_search(
    method: str,
    *,
    weights: FusionWeights | None = None,
    reranker_config: RerankerConfig | None = None,
) -> Callable[..., list[dict]]:
    if method not in {value.value for value in SearchMethod} | {RERANK_METHOD}:
        raise ValueError(f"unsupported retrieval method: {method}")
    config = reranker_config or RerankerConfig()
    backend = TransformersRerankerBackend(config) if method == RERANK_METHOD else None
    fusion_weights = weights or FusionWeights(0.5, 0.5)

    def retrieve(
        retrieval_question: str,
        dense_vector: list[float],
        sparse_vector: dict[str, list],
        top_k: int,
        metadata_filter: dict[str, str] | None,
        settings: Settings,
    ) -> list[dict]:
        sparse_indices = tuple(int(value) for value in sparse_vector.get("indices", []))
        sparse_values = tuple(float(value) for value in sparse_vector.get("values", []))
        search_method = SearchMethod.RRF if method == RERANK_METHOD else SearchMethod(method)
        hits = search(
            QdrantClient(url=settings.qdrant_url),
            SearchRequest(
                collection_name=settings.qdrant_collection,
                method=search_method,
                dense_vector=tuple(dense_vector),
                sparse_indices=sparse_indices,
                sparse_values=sparse_values,
                candidate_limit=top_k,
                weights=(fusion_weights if search_method is SearchMethod.WEIGHTED_RRF else None),
                query_filter=_metadata_filter(metadata_filter),
            ),
        )
        if method == RERANK_METHOD:
            if backend is None:
                raise RuntimeError("reranker backend is unavailable")
            hits = rerank_hits(
                retrieval_question,
                hits,
                backend=backend,
                config=config,
            ).hits
        return [{"id": hit.id, "score": hit.score, "payload": hit.payload} for hit in hits]

    return retrieve


def _metadata_filter(values: dict[str, str] | None) -> models.Filter | None:
    if not values:
        return None
    return models.Filter(
        must=[
            models.FieldCondition(
                key=key,
                match=models.MatchValue(value=_coerce(value)),
            )
            for key, value in values.items()
        ]
    )


def _coerce(value: str) -> int | str:
    try:
        return int(value)
    except ValueError:
        return value
