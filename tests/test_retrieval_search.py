from dataclasses import dataclass

import pytest
from qdrant_client import models

from app.retrieval_search import (
    FusionWeights,
    SearchHit,
    SearchMethod,
    SearchRequest,
    collapse_parent_hits,
    search,
)


@dataclass(frozen=True)
class FakePoint:
    id: int
    score: float
    payload: dict


@dataclass(frozen=True)
class FakeResponse:
    points: list[FakePoint]


class FakeClient:
    def __init__(self, points=None):
        self.calls = []
        self.points = points or []

    def query_points(self, **kwargs):
        self.calls.append(kwargs)
        return FakeResponse(self.points)


def make_request(method, *, candidate_limit=20, weights=None):
    return SearchRequest(
        collection_name="policy",
        method=method,
        dense_vector=(0.1, 0.2),
        sparse_indices=(3, 7),
        sparse_values=(1.0, 2.0),
        candidate_limit=candidate_limit,
        weights=weights,
    )


def test_search_uses_named_dense_vector_for_dense_method():
    # Given
    client = FakeClient([FakePoint(1, 0.9, {"chunk_id": "jo-1-hang-1"})])

    # When
    hits = search(client, make_request(SearchMethod.DENSE))

    # Then
    call = client.calls[0]
    assert call["query"] == [0.1, 0.2]
    assert call["using"] == "dense"
    assert call["limit"] == 20
    assert hits == (SearchHit(id=1, score=0.9, payload={"chunk_id": "jo-1-hang-1"}),)


def test_search_uses_named_sparse_vector_for_bm25_method():
    # Given
    client = FakeClient()

    # When
    search(client, make_request(SearchMethod.BM25))

    # Then
    call = client.calls[0]
    assert call["query"] == models.SparseVector(indices=[3, 7], values=[1.0, 2.0])
    assert call["using"] == "bm25"
    assert call["limit"] == 20


@pytest.mark.parametrize(
    ("method", "expected_query"),
    [
        (SearchMethod.RRF, models.FusionQuery(fusion=models.Fusion.RRF)),
        (SearchMethod.DBSF, models.FusionQuery(fusion=models.Fusion.DBSF)),
    ],
)
def test_search_uses_equal_dense_and_sparse_prefetch_limits_for_fusion(method, expected_query):
    # Given
    client = FakeClient()

    # When
    search(client, make_request(method, candidate_limit=12))

    # Then
    call = client.calls[0]
    assert call["query"] == expected_query
    assert [prefetch.limit for prefetch in call["prefetch"]] == [12, 12]
    assert [prefetch.using for prefetch in call["prefetch"]] == ["dense", "bm25"]


def test_search_passes_explicit_weights_to_weighted_rrf():
    # Given
    client = FakeClient()
    weights = FusionWeights(dense=0.75, sparse=0.25)

    # When
    search(client, make_request(SearchMethod.WEIGHTED_RRF, weights=weights))

    # Then
    query = client.calls[0]["query"]
    assert query == models.RrfQuery(rrf=models.Rrf(weights=[0.75, 0.25]))


def test_collapse_parent_hits_preserves_first_ranked_child_for_each_parent():
    # Given
    hits = (
        SearchHit(1, 0.9, {"chunk_id": "jo-7-hang-1", "parent_id": "jo-7"}),
        SearchHit(2, 0.8, {"chunk_id": "jo-7-hang-2", "parent_id": "jo-7"}),
        SearchHit(3, 0.7, {"chunk_id": "jo-13-hang-1", "parent_id": "jo-13"}),
        SearchHit(4, 0.6, {"chunk_id": "jo-8-hang-1", "parent_id": "jo-8"}),
    )

    # When
    parents = collapse_parent_hits(hits, limit=2)

    # Then
    assert [parent.parent_id for parent in parents] == ["jo-7", "jo-13"]
    assert [parent.child_id for parent in parents] == ["jo-7-hang-1", "jo-13-hang-1"]


def test_search_rejects_bm25_request_without_sparse_values():
    # Given
    request = SearchRequest(
        collection_name="policy",
        method=SearchMethod.BM25,
        dense_vector=(0.1,),
        sparse_indices=(),
        sparse_values=(),
        candidate_limit=5,
    )

    # When
    with pytest.raises(ValueError) as error:
        search(FakeClient(), request)

    # Then
    assert "sparse" in str(error.value)
