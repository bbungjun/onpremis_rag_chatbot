import json

import pytest

from app.retrieval_evaluation import EvaluationRecord
from app.retrieval_metrics import ranking_metrics
from app.retrieval_reports import (
    append_result,
    create_run_directory,
    render_summary,
    write_run_metadata,
)


def record(case_id, method, predicted):
    return EvaluationRecord(
        case_id=case_id,
        method=method,
        status="success",
        gold_parent_ids=("jo-1",),
        predicted_parent_ids=tuple(predicted),
        predicted_child_ids=(),
        metrics=ranking_metrics(("jo-1",), predicted),
        timing_ms={"qdrant_search": 10.0, "reranker": 0.0},
    )


def test_run_artifacts_exclude_questions_and_flush_jsonl(tmp_path, monkeypatch):
    # Given
    output = create_run_directory(tmp_path, "run-1")
    sync_calls = []
    monkeypatch.setattr("app.retrieval_reports.os.fsync", sync_calls.append)

    # When
    write_run_metadata(
        output / "run.json",
        {
            "run_id": "run-1",
            "dataset_sha256": "abc",
            "methods": ["dense"],
        },
    )
    append_result(output / "results.jsonl", record("q1", "dense", ("jo-1",)))

    # Then
    metadata = json.loads((output / "run.json").read_text(encoding="utf-8"))
    assert metadata == {
        "dataset_sha256": "abc",
        "methods": ["dense"],
        "run_id": "run-1",
    }
    result_text = (output / "results.jsonl").read_text(encoding="utf-8")
    assert "question" not in result_text
    assert "jo-1" in result_text
    assert len(sync_calls) == 1


def test_create_run_directory_rejects_unsafe_run_id(tmp_path):
    with pytest.raises(ValueError):
        create_run_directory(tmp_path, "../escape")


def test_summary_reports_metrics_errors_and_paired_bootstrap():
    # Given
    records = (
        record("q1", "dense", ("jo-9",)),
        record("q1", "rrf", ("jo-1",)),
        EvaluationRecord(
            case_id="q2",
            method="rrf",
            status="error",
            gold_parent_ids=("jo-2",),
            predicted_parent_ids=(),
            predicted_child_ids=(),
            metrics=None,
            timing_ms={},
            error="RuntimeError: unavailable",
        ),
    )

    # When
    summary = render_summary(records, baseline="dense", seed=7, samples=100)

    # Then
    assert "| dense | 0.0000" in summary
    assert "| rrf | 1.0000" in summary
    assert "오류 1건" in summary
    assert "rrf vs dense" in summary
    assert "95% CI" in summary
