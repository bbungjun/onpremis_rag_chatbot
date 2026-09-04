from app.reranker import RerankerConfig, rerank_hits
from app.retrieval_search import SearchHit


class FakeBackend:
    def __init__(self, scores):
        self.scores = scores
        self.calls = []

    def score(self, pairs, *, batch_size, max_length):
        self.calls.append((pairs, batch_size, max_length))
        return self.scores


def test_reranker_passes_only_query_and_child_text_to_backend():
    # Given
    backend = FakeBackend([0.2])
    hits = (
        SearchHit(
            1,
            0.8,
            {
                "chunk_id": "jo-1-hang-1",
                "parent_id": "jo-1",
                "text": "child text",
                "parent_text": "must not be passed",
                "gold_answer": "must not be passed",
            },
        ),
    )

    # When
    rerank_hits("retrieval question", hits, backend=backend, config=RerankerConfig())

    # Then
    assert backend.calls == [((("retrieval question", "child text"),), 8, 1024)]


def test_reranker_orders_children_by_score_and_keeps_payload():
    # Given
    backend = FakeBackend([0.1, 0.9, 0.4])
    hits = tuple(
        SearchHit(index, 1.0 - index / 10, {"chunk_id": f"child-{index}", "text": text})
        for index, text in enumerate(("a", "b", "c"), start=1)
    )

    # When
    result = rerank_hits("query", hits, backend=backend, config=RerankerConfig())

    # Then
    assert [hit.payload["chunk_id"] for hit in result.hits] == ["child-2", "child-3", "child-1"]
    assert [hit.score for hit in result.hits] == [0.9, 0.4, 0.1]
    assert result.elapsed_ms >= 0


def test_reranker_rejects_missing_child_text():
    hits = (SearchHit(1, 0.8, {"chunk_id": "child-1", "parent_text": "wrong"}),)

    try:
        rerank_hits("query", hits, backend=FakeBackend([1.0]), config=RerankerConfig())
    except ValueError as error:
        assert "text" in str(error)
    else:
        raise AssertionError("missing child text must be rejected")
