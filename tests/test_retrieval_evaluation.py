from app.retrieval_evaluation import (
    QueryRepresentation,
    RetrievalCase,
    RetrievalOutcome,
    evaluate_quality,
)
from app.retrieval_search import SearchHit


def test_evaluate_quality_reuses_one_representation_for_all_methods():
    # Given
    cases = (RetrievalCase("q1", "휴가 기한은?", ("jo-1",)),)
    represented = []
    searched = []

    def represent(question):
        represented.append(question)
        return QueryRepresentation(question, (0.1,), (1,), (2.0,), 3.0, 1.0)

    def retrieve(method, representation):
        searched.append((method, representation))
        return RetrievalOutcome(
            (SearchHit(1, 0.9, {"chunk_id": "jo-1-hang-1", "parent_id": "jo-1"}),),
            4.0,
        )

    # When
    records = evaluate_quality(
        cases,
        methods=("dense", "rrf"),
        top_k=5,
        represent=represent,
        retrieve=retrieve,
    )

    # Then
    assert represented == ["휴가 기한은?"]
    assert [method for method, _ in searched] == ["dense", "rrf"]
    assert len({id(representation) for _, representation in searched}) == 1
    assert [record.method for record in records] == ["dense", "rrf"]
    assert all(record.status == "success" for record in records)
    assert all(record.metrics.recall_at_5 == 1 for record in records)


def test_evaluate_quality_persists_method_error_without_scoring_it():
    # Given
    written = []

    def retrieve(method, _representation):
        if method == "dbsf":
            raise RuntimeError("unsupported")
        return RetrievalOutcome((), 2.0)

    # When
    records = evaluate_quality(
        (RetrievalCase("q1", "질문", ("jo-1",)),),
        methods=("dense", "dbsf"),
        top_k=5,
        represent=lambda question: QueryRepresentation(question, (0.1,), (1,), (1.0,), 1.0, 1.0),
        retrieve=retrieve,
        record_sink=written.append,
    )

    # Then
    assert records == tuple(written)
    assert records[0].status == "success"
    assert records[1].status == "error"
    assert records[1].metrics is None
    assert records[1].error == "RuntimeError: unsupported"
