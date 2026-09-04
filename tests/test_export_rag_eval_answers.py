from __future__ import annotations

import hashlib
import json
from types import SimpleNamespace

import pytest
from qdrant_client.http.exceptions import ApiException

from scripts import evaluate_local_judge as runner
from scripts import export_rag_eval_answers as exporter


def test_run_export_writes_answer_case_data_and_source_recall(tmp_path):
    case = runner.EvalCase(
        "q1",
        "leave",
        "When must annual leave be requested?",
        ("jo-39",),
        "Submit the request at least three business days in advance.",
    )

    output = exporter.run_export(
        [case],
        answer_model="qwen3:4b",
        top_k=5,
        output_dir=tmp_path,
        run_id="test",
        answer=lambda question, *, top_k: {
            "answer": "Submit the request at least three business days in advance.",
            "sources": [{"chunk_id": "doc:reg::jo-39"}],
        },
    )

    record = json.loads((output / "answers.jsonl").read_text(encoding="utf-8"))
    assert record == {
        "status": "answered",
        "case": {
            "id": "q1",
            "type": "leave",
            "question": "When must annual leave be requested?",
            "gold_answer": "Submit the request at least three business days in advance.",
            "gold_jo": ["jo-39"],
        },
        "answer": "Submit the request at least three business days in advance.",
        "source_ids": ["doc:reg::jo-39"],
        "source_recall": 1.0,
        "elapsed_ms": record["elapsed_ms"],
    }
    assert isinstance(record["elapsed_ms"], int)
    assert record["elapsed_ms"] >= 0

    metadata = json.loads((output / "run.json").read_text(encoding="utf-8"))
    expected_dataset = json.dumps(
        [
            {
                "id": "q1",
                "type": "leave",
                "question": "When must annual leave be requested?",
                "gold_jo": ["jo-39"],
                "answer": "Submit the request at least three business days in advance.",
            }
        ],
        ensure_ascii=False,
        sort_keys=True,
    )
    assert metadata["run_id"] == "test"
    assert metadata["answer_model"] == "qwen3:4b"
    assert metadata["top_k"] == 5
    assert metadata["case_count"] == 1
    assert (
        metadata["dataset_sha256"] == hashlib.sha256(expected_dataset.encode("utf-8")).hexdigest()
    )
    assert metadata["created_at"].endswith("+00:00")


def test_run_export_records_response_validation_error_and_continues(tmp_path):
    cases = [
        runner.EvalCase("q1", "leave", "first", ("jo-1",), "gold one"),
        runner.EvalCase("q2", "leave", "second", ("jo-2",), "gold two"),
    ]

    def answer(question: str, *, top_k: int) -> dict[str, object]:
        if question == "first":
            return {"answer": "", "sources": []}
        return {"answer": "generated", "sources": [{"chunk_id": "jo-2"}]}

    output = exporter.run_export(
        cases,
        answer_model="qwen3:4b",
        top_k=5,
        output_dir=tmp_path,
        run_id="errors",
        answer=answer,
    )

    records = [
        json.loads(line)
        for line in (output / "answers.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert [record["status"] for record in records] == ["answer_error", "answered"]
    assert records[0]["case"] == {
        "id": "q1",
        "type": "leave",
        "question": "first",
        "gold_answer": "gold one",
        "gold_jo": ["jo-1"],
    }
    assert records[0]["answer_error"] == "ValueError: answer must be a non-empty string"
    assert records[1]["source_recall"] == 1.0


def test_run_export_records_qdrant_api_error_and_continues(tmp_path):
    cases = [
        runner.EvalCase("q1", "leave", "first", ("jo-1",), "gold one"),
        runner.EvalCase("q2", "leave", "second", ("jo-2",), "gold two"),
    ]

    def answer(question: str, *, top_k: int) -> dict[str, object]:
        if question == "first":
            raise ApiException("Qdrant unavailable")
        return {"answer": "generated", "sources": [{"chunk_id": "jo-2"}]}

    output = exporter.run_export(
        cases,
        answer_model="qwen3:4b",
        top_k=5,
        output_dir=tmp_path,
        run_id="qdrant-error",
        answer=answer,
    )

    records = [
        json.loads(line)
        for line in (output / "answers.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert [record["status"] for record in records] == ["answer_error", "answered"]
    assert records[0]["answer_error"] == "ApiException: Qdrant unavailable"


@pytest.mark.parametrize(
    "run_id",
    ["", "   ", ".", "..", "../outside", "nested/run", r"nested\run", "/outside", r"C:\\outside"],
)
def test_run_export_rejects_unsafe_run_id(tmp_path, run_id):
    case = runner.EvalCase("q1", "leave", "question", ("jo-1",), "gold")

    with pytest.raises(ValueError, match="run_id must be a single safe directory name"):
        exporter.run_export(
            [case],
            answer_model="qwen3:4b",
            top_k=5,
            output_dir=tmp_path,
            run_id=run_id,
            answer=lambda question, *, top_k: pytest.fail("answer must not run"),
        )

    assert not (tmp_path / "outside").exists()


def test_run_export_forwards_each_question_and_top_k(tmp_path):
    cases = [
        runner.EvalCase("q1", "leave", "first", ("jo-1",), "gold one"),
        runner.EvalCase("q2", "leave", "second", ("jo-2",), "gold two"),
    ]
    calls: list[tuple[str, int]] = []

    def answer(question: str, *, top_k: int) -> dict[str, object]:
        calls.append((question, top_k))
        return {"answer": "generated", "sources": []}

    exporter.run_export(
        cases,
        answer_model="qwen3:4b",
        top_k=7,
        output_dir=tmp_path,
        run_id="forwarding",
        answer=answer,
    )

    assert calls == [("first", 7), ("second", 7)]


def test_run_export_persists_completed_record_before_interruption(tmp_path):
    cases = [
        runner.EvalCase("q1", "leave", "first", ("jo-1",), "gold one"),
        runner.EvalCase("q2", "leave", "second", ("jo-2",), "gold two"),
    ]

    def answer(question: str, *, top_k: int) -> dict[str, object]:
        if question == "second":
            raise KeyboardInterrupt
        return {"answer": "generated", "sources": [{"chunk_id": "jo-1"}]}

    with pytest.raises(KeyboardInterrupt):
        exporter.run_export(
            cases,
            answer_model="qwen3:4b",
            top_k=5,
            output_dir=tmp_path,
            run_id="interrupted",
            answer=answer,
        )

    records = [
        json.loads(line)
        for line in (tmp_path / "interrupted" / "answers.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert [record["case"]["id"] for record in records] == ["q1"]


def test_cli_rejects_output_outside_local_judge_report_root(tmp_path, capsys):
    with pytest.raises(SystemExit) as exc_info:
        exporter.main(["--output-dir", str(tmp_path)])

    assert exc_info.value.code == 2
    assert "--output-dir must be inside reports/local-judge" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("statuses", "expected_exit_code"),
    [(["answer_error"], 1), (["answer_error", "answered"], 0)],
)
def test_cli_exit_code_reflects_answered_records(
    tmp_path, monkeypatch, statuses, expected_exit_code
):
    output = tmp_path / "export"
    output.mkdir()
    (output / "answers.jsonl").write_text(
        "".join(json.dumps({"status": status}) + "\n" for status in statuses),
        encoding="utf-8",
    )
    case = runner.EvalCase("q1", "leave", "question", ("jo-1",), "gold")
    monkeypatch.setattr(exporter, "run_export", lambda *_, **__: output)

    result = exporter.main(
        [],
        load_cases_callable=lambda _: [case],
        settings_factory=lambda: SimpleNamespace(llm_model="qwen3:4b"),
        answer_question_callable=lambda question, *, top_k, settings: {},
    )

    assert result == expected_exit_code
