from dataclasses import dataclass
from enum import StrEnum
from typing import assert_never

from qdrant_client import QdrantClient, models

from app.vector_store import DENSE_VECTOR_NAME, SPARSE_VECTOR_NAME


class SearchMethod(StrEnum):
    DENSE = "dense"
    BM25 = "bm25"
    RRF = "rrf"
    WEIGHTED_RRF = "weighted_rrf"
    DBSF = "dbsf"


@dataclass(frozen=True, slots=True)
class FusionWeights:
    dense: float
    sparse: float

    def __post_init__(self) -> None:
        if self.dense < 0 or self.sparse < 0:
            raise ValueError("fusion weights must not be negative")
        if self.dense + self.sparse <= 0:
            raise ValueError("at least one fusion weight must be positive")


@dataclass(frozen=True, slots=True)
class SearchRequest:
    collection_name: str
    method: SearchMethod
    dense_vector: tuple[float, ...]
    sparse_indices: tuple[int, ...]
    sparse_values: tuple[float, ...]
    candidate_limit: int
    weights: FusionWeights | None = None
    query_filter: models.Filter | None = None


@dataclass(frozen=True, slots=True)
class SearchHit:
    id: int | str
    score: float
    payload: dict[str, object]


@dataclass(frozen=True, slots=True)
class ParentHit:
    parent_id: str
    child_id: str
    score: float
    payload: dict[str, object]


def search(client: QdrantClient, request: SearchRequest) -> tuple[SearchHit, ...]:
    _validate_request(request)

    common = {
        "collection_name": request.collection_name,
        "limit": request.candidate_limit,
        "with_payload": True,
        "with_vectors": False,
    }
    match request.method:
        case SearchMethod.DENSE:
            response = client.query_points(
                query=list(request.dense_vector),
                using=DENSE_VECTOR_NAME,
                query_filter=request.query_filter,
                **common,
            )
        case SearchMethod.BM25:
            response = client.query_points(
                query=_sparse_vector(request),
                using=SPARSE_VECTOR_NAME,
                query_filter=request.query_filter,
                **common,
            )
        case SearchMethod.RRF | SearchMethod.DBSF | SearchMethod.WEIGHTED_RRF:
            response = client.query_points(
                prefetch=_hybrid_prefetch(request),
                query=_fusion_query(request),
                **common,
            )
        case unreachable:
            assert_never(unreachable)

    return tuple(
        SearchHit(
            id=point.id,
            score=point.score,
            payload=dict(point.payload or {}),
        )
        for point in response.points
    )


def collapse_parent_hits(hits: tuple[SearchHit, ...], limit: int) -> tuple[ParentHit, ...]:
    if limit <= 0:
        raise ValueError("limit must be greater than 0")

    parents: list[ParentHit] = []
    seen: set[str] = set()
    for hit in hits:
        child_id = _required_payload_text(hit.payload, "chunk_id")
        parent_id = _required_payload_text(hit.payload, "parent_id", child_id)
        if parent_id in seen:
            continue
        seen.add(parent_id)
        parents.append(
            ParentHit(
                parent_id=parent_id,
                child_id=child_id,
                score=hit.score,
                payload=hit.payload,
            )
        )
        if len(parents) == limit:
            break
    return tuple(parents)


def _validate_request(request: SearchRequest) -> None:
    if not request.collection_name.strip():
        raise ValueError("collection_name must not be empty")
    if request.candidate_limit <= 0:
        raise ValueError("candidate_limit must be greater than 0")
    if request.method is not SearchMethod.BM25 and not request.dense_vector:
        raise ValueError("dense vector must not be empty")
    if request.method is not SearchMethod.DENSE:
        if not request.sparse_indices or not request.sparse_values:
            raise ValueError("sparse vector must not be empty")
        if len(request.sparse_indices) != len(request.sparse_values):
            raise ValueError("sparse indices and values must have equal lengths")
    if request.method is SearchMethod.WEIGHTED_RRF and request.weights is None:
        raise ValueError("weighted RRF requires fusion weights")


def _sparse_vector(request: SearchRequest) -> models.SparseVector:
    return models.SparseVector(
        indices=list(request.sparse_indices),
        values=list(request.sparse_values),
    )


def _hybrid_prefetch(request: SearchRequest) -> list[models.Prefetch]:
    return [
        models.Prefetch(
            query=list(request.dense_vector),
            using=DENSE_VECTOR_NAME,
            limit=request.candidate_limit,
            filter=request.query_filter,
        ),
        models.Prefetch(
            query=_sparse_vector(request),
            using=SPARSE_VECTOR_NAME,
            limit=request.candidate_limit,
            filter=request.query_filter,
        ),
    ]


def _fusion_query(
    request: SearchRequest,
) -> models.FusionQuery | models.RrfQuery:
    match request.method:
        case SearchMethod.RRF:
            return models.FusionQuery(fusion=models.Fusion.RRF)
        case SearchMethod.DBSF:
            return models.FusionQuery(fusion=models.Fusion.DBSF)
        case SearchMethod.WEIGHTED_RRF:
            if request.weights is None:
                raise ValueError("weighted RRF requires fusion weights")
            return models.RrfQuery(
                rrf=models.Rrf(weights=[request.weights.dense, request.weights.sparse])
            )
        case SearchMethod.DENSE | SearchMethod.BM25:
            raise ValueError(f"{request.method} is not a fusion method")
        case unreachable:
            assert_never(unreachable)


def _required_payload_text(payload: dict[str, object], key: str, default: str | None = None) -> str:
    value = payload.get(key, default)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"search payload field must be non-empty text: {key}")
    return value
