from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

from app.local_judge import JudgeVerdict
from scripts import evaluate_local_judge as runner


def test_cli_help_runs_from_repository_root():
    completed = subprocess.run(
        [sys.executable, "scripts/evaluate_local_judge.py", "--help"],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0
    assert "Evaluate RAG answers with a separate local LLM Judge." in completed.stdout


def test_cli_rejects_qwen_judge_model_without_traceback():
    completed = subprocess.run(
        [
            sys.executable,
            "scripts/evaluate_local_judge.py",
            "--judge-model",
            "qwen3:4b-instruct",
        ],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 2
    assert "judge_model must be a supported local judge model" in completed.stderr
    assert "Traceback" not in completed.stderr


def test_load_cases_reads_existing_gold_question_schema(tmp_path):
    path = tmp_path / "cases.jsonl"
    path.write_text(
        '{"id":"q1","type":"일상어","question":"연차는 언제 신청하나요?",'
        '"gold_jo":["jo-39"],"answer":"최소 3영업일 전 신청합니다."}\n',
        encoding="utf-8",
    )

    assert runner.load_cases(path) == [
        runner.EvalCase(
            id="q1",
            type="일상어",
            question="연차는 언제 신청하나요?",
            gold_jo=("jo-39",),
            answer="최소 3영업일 전 신청합니다.",
        )
    ]


def test_load_cases_reads_all_committed_evaluation_cases():
    cases = runner.load_cases(Path("datasets/eval/qa_set.jsonl"))

    assert len(cases) == 50
    assert len({case.id for case in cases}) == 50
    assert cases[0].id == "q01"
    assert cases[-1].id == "q50"


def test_committed_evaluation_cases_are_natural_and_grounded():
    cases = runner.load_cases(Path("datasets/eval/qa_set.jsonl"))
    regulation = Path("datasets/docs/regulations.md").read_text(encoding="utf-8")
    regulation_ids = {f"jo-{number}" for number in re.findall(r"^\*\*제(\d+)조", regulation, re.M)}

    assert [case.id for case in cases] == [f"q{index:02d}" for index in range(1, 51)]
    assert all(case.type == "일상어" for case in cases)
    assert all(re.search(r"제\s*\d+\s*조", case.question) is None for case in cases)
    assert all(set(case.gold_jo) <= regulation_ids for case in cases)


def test_source_recall_normalizes_returned_parent_ids():
    recall = runner.source_recall(
        ("jo-39", "jo-40"),
        [{"chunk_id": "doc:reg::jo-39"}, {"chunk_id": "jo-8"}],
    )

    assert recall == 0.5


def test_run_evaluation_writes_judged_record_and_summary(tmp_path):
    cases = [
        runner.EvalCase(
            id="q1",
            type="일상어",
            question="연차는 언제 신청하나요?",
            gold_jo=("jo-39",),
            answer="최소 3영업일 전 신청합니다.",
        )
    ]

    output = runner.run_evaluation(
        cases,
        answer_model="qwen3:4b-instruct",
        judge_model="exaone3.5:7.8b",
        base_url="http://ollama.local",
        num_ctx=4096,
        output_dir=tmp_path,
        run_id="test-run",
        answer=lambda question, *, top_k: {
            "answer": "최소 3영업일 전 신청합니다.",
            "sources": [{"chunk_id": "doc:reg::jo-39"}],
        },
        judge=lambda **_: JudgeVerdict(2, 2, 2, "정답 및 출처가 일치합니다."),
    )

    record = json.loads((output / "results.jsonl").read_text(encoding="utf-8"))
    summary = (output / "summary.md").read_text(encoding="utf-8")

    assert record["status"] == "judged"
    assert record["source_recall"] == 1.0
    assert record["verdict"]["total"] == 6
    assert record["models"] == {
        "answer": "qwen3:4b-instruct",
        "judge": "exaone3.5:7.8b",
    }
    assert "Judged cases: 1" in summary
    assert "Mean Judge total: 6.00 / 6" in summary
    assert "Mean source recall: 1.000" in summary
    metadata = json.loads((output / "run.json").read_text(encoding="utf-8"))
    assert metadata["run_id"] == "test-run"
    assert metadata["settings"] == {"num_ctx": 4096, "top_k": 5}
    assert metadata["dataset"]["case_count"] == 1


def test_cli_rejects_report_output_outside_ignored_report_root(tmp_path, capsys):
    with pytest.raises(SystemExit) as exc_info:
        runner.main(
            [
                "--judge-model",
                "exaone3.5:7.8b",
                "--output-dir",
                str(tmp_path),
            ]
        )

    assert exc_info.value.code == 2
    assert "--output-dir must be inside reports/local-judge" in capsys.readouterr().err


def test_run_evaluation_records_case_error_and_keeps_other_judgments(tmp_path):
    cases = [
        runner.EvalCase("q1", "일상어", "성공 질문", ("jo-1",), "정답"),
        runner.EvalCase("q2", "일상어", "실패 질문", ("jo-2",), "정답"),
    ]

    def answer(question: str, *, top_k: int) -> dict:
        if question == "실패 질문":
            raise RuntimeError("Ollama unavailable")
        return {"answer": "정답", "sources": [{"chunk_id": "jo-1"}]}

    output = runner.run_evaluation(
        cases,
        answer_model="qwen3:4b-instruct",
        judge_model="exaone3.5:7.8b",
        base_url="http://ollama.local",
        num_ctx=4096,
        output_dir=tmp_path,
        run_id="error-run",
        answer=answer,
        judge=lambda **_: JudgeVerdict(2, 2, 2, "일치"),
    )

    records = [
        json.loads(line)
        for line in (output / "results.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    summary = (output / "summary.md").read_text(encoding="utf-8")

    assert [record["status"] for record in records] == ["judged", "answer_error"]
    assert records[1]["answer_error"] == "RuntimeError: Ollama unavailable"
    assert "Answered cases: 1" in summary
    assert "Answer errors: 1" in summary


def test_run_evaluation_preserves_source_recall_when_judging_fails(tmp_path):
    case = runner.EvalCase("q1", "일상어", "연차는?", ("jo-39",), "3일 전")

    output = runner.run_evaluation(
        [case],
        answer_model="qwen3:4b-instruct",
        judge_model="exaone3.5:7.8b",
        base_url="http://ollama.local",
        num_ctx=4096,
        output_dir=tmp_path,
        run_id="judge-error-run",
        answer=lambda question, *, top_k: {
            "answer": "최소 3영업일 전 신청합니다.",
            "sources": [{"chunk_id": "doc:reg::jo-39"}],
        },
        judge=lambda **_: (_ for _ in ()).throw(RuntimeError("Judge unavailable")),
    )

    record = json.loads((output / "results.jsonl").read_text(encoding="utf-8"))
    summary = (output / "summary.md").read_text(encoding="utf-8")

    assert record["status"] == "judge_error"
    assert record["answer"] == "최소 3영업일 전 신청합니다."
    assert record["source_ids"] == ["doc:reg::jo-39"]
    assert record["source_recall"] == 1.0
    assert record["judge_error"] == "RuntimeError: Judge unavailable"
    assert "Answered cases: 1" in summary
    assert "Judged cases: 0" in summary
    assert "Mean source recall: 1.000" in summary


def test_run_evaluation_persists_completed_records_before_interruption(tmp_path):
    cases = [
        runner.EvalCase("q1", "일상어", "첫 질문", ("jo-1",), "정답"),
        runner.EvalCase("q2", "일상어", "둘째 질문", ("jo-2",), "정답"),
    ]

    def answer(question: str, *, top_k: int) -> dict:
        if question == "둘째 질문":
            raise KeyboardInterrupt
        return {"answer": "정답", "sources": [{"chunk_id": "jo-1"}]}

    with pytest.raises(KeyboardInterrupt):
        runner.run_evaluation(
            cases,
            answer_model="qwen3:4b-instruct",
            judge_model="exaone3.5:7.8b",
            base_url="http://ollama.local",
            num_ctx=4096,
            output_dir=tmp_path,
            run_id="interrupted-run",
            answer=answer,
            judge=lambda **_: JudgeVerdict(2, 2, 2, "일치"),
        )

    records = [
        json.loads(line)
        for line in (tmp_path / "interrupted-run" / "results.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]

    assert [record["case"]["id"] for record in records] == ["q1"]


def test_summary_escapes_model_controlled_rationale_and_lists_judge_errors():
    summary = runner.summarize_records(
        [
            {
                "status": "judged",
                "case": {"id": "q1", "type": "일상어"},
                "source_recall": 1.0,
                "verdict": {
                    "correctness": 2,
                    "groundedness": 2,
                    "completeness": 2,
                    "total": 6,
                    "rationale": (
                        "정상\n# 위조 제목 [링크](https://example.invalid) "
                        '<img src="https://example.invalid/tracker"> & 안전'
                    ),
                },
            },
            {
                "status": "judge_error",
                "case": {"id": "q2", "type": "일상어"},
                "source_recall": 0.5,
                "judge_error": "RuntimeError: unavailable",
            },
            {
                "status": "answer_error",
                "case": {"id": "q3", "type": "일상어"},
                "answer_error": "RuntimeError: <token> & unavailable",
            },
        ]
    )

    rendered = runner.render_summary(summary)

    assert (
        "정상 # 위조 제목 \\[링크\\](https://example.invalid) "
        '\\<img src="https://example.invalid/tracker"\\> \\& 안전'
    ) in rendered
    assert "## Judge errors" in rendered
    assert "q2: RuntimeError: unavailable" in rendered
    assert "## Answer errors" in rendered
    assert "q3: RuntimeError: \\<token\\> \\& unavailable" in rendered


def test_run_evaluation_rejects_qwen_judge_model_before_callbacks(tmp_path):
    case = runner.EvalCase("q1", "일상어", "연차는?", ("jo-39",), "3일 전")

    with pytest.raises(ValueError, match="supported local judge"):
        runner.run_evaluation(
            [case],
            answer_model="qwen3:4b-instruct",
            judge_model="qwen3:4b-instruct",
            base_url="http://ollama.local",
            num_ctx=4096,
            output_dir=tmp_path,
            run_id="invalid-model",
            answer=lambda question, *, top_k: pytest.fail("answer must not run"),
            judge=lambda **_: pytest.fail("judge must not run"),
        )
