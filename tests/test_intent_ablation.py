from dataclasses import replace

import pytest

from app.config import Settings
from app.intent_ablation import ARMS, freeze_case, paired_summary, run_generation


def settings():
    return Settings(
        "http://ollama",
        "qwen3:4b-instruct",
        "bge-m3",
        "http://qdrant",
        "chunks",
        5,
        0.2,
        4096,
        2048,
        "off",
    )


def hit(number=39, text="연차는 최소 3영업일 전에 신청한다."):
    return {
        "score": 1.0,
        "payload": {
            "parent_id": f"jo-{number}",
            "parent_text": text,
            "jo": str(number),
            "source_path": "regulations.md",
        },
    }


def test_frozen_context_and_conditions_are_identical_across_arms():
    calls = []
    case = {"id": "q", "type": "일상어", "question": "내일 연차 신청해도 될까요?"}

    def retrieve(question):
        calls.append(question)
        return [hit()]

    result = freeze_case(case, "eligibility_check", settings(), retrieve)
    assert calls == [case["question"]]
    assert len({p.split("[original_question]")[0] for p in result["prompts"].values()}) == 1
    assert result["prompts"][ARMS[1]] == result["prompts"][ARMS[2]]
    assert result["canonical"][ARMS[0]] == case["question"]
    assert "내일" in result["canonical"][ARMS[2]]
    assert "gold" not in result["prompts"][ARMS[2]]


def test_gold_intervention_does_not_put_reference_answer_in_prompt():
    case = {"id": "q", "question": "월급 언제임?", "answer": "REFERENCE_ONLY", "gold_jo": ["jo-43"]}
    result = freeze_case(case, "deadline_lookup", settings(), lambda q: [hit(43)])
    assert result["predicted_intent"] == "general_qa"
    assert "기한" in result["canonical"][ARMS[2]]
    assert all("REFERENCE_ONLY" not in p for p in result["prompts"].values())


def test_joint_budget_drops_same_parent_and_rejects_oversized_single_parent():
    case = {"id": "q", "question": "연차 신청은 언제까지?"}
    small = replace(settings(), num_ctx=1500)
    result = freeze_case(
        case, "deadline_lookup", small, lambda q: [hit(39, "가" * 700), hit(40, "나" * 700)]
    )
    assert len(result["parents"]) == 1
    assert all(len(p) <= result["budget_chars"] for p in result["prompts"].values())
    with pytest.raises(ValueError, match="budget"):
        freeze_case(case, "deadline_lookup", small, lambda q: [hit(39, "가" * 4000)])


def test_generation_persists_failures_and_resume_skips_existing(tmp_path):
    from app.intent_ablation import read_jsonl

    case = freeze_case(
        {"id": "q", "question": "연차 신청은 언제까지?"},
        "deadline_lookup",
        settings(),
        lambda q: [hit()],
    )
    calls = []

    def generate(system, user, seed):
        calls.append((system, user, seed))
        if len(calls) == 2:
            raise RuntimeError("offline")
        return {"message": {"content": "제39조에 따르면 3영업일 전"}, "done_reason": "stop"}

    path = tmp_path / "answers.jsonl"
    run_generation([case], path, generate, repeats=1)
    records = read_jsonl(path)
    assert len(records) == 3
    assert len({r["seed"] for r in records}) == 1
    assert sum(r["status"] == "generation_error" for r in records) == 1
    run_generation([case], path, generate, repeats=1)
    assert len(calls) == 3


def test_empty_retrieval_never_calls_qwen(tmp_path):
    from app.intent_ablation import read_jsonl

    case = freeze_case(
        {"id": "q", "question": "연차 신청은 언제까지?"},
        "deadline_lookup",
        settings(),
        lambda q: [],
    )

    def forbidden(*args):
        pytest.fail("must not generate without context")

    run_generation([case], tmp_path / "answers.jsonl", forbidden, repeats=1)
    assert all(r["status"] == "no_context" for r in read_jsonl(tmp_path / "answers.jsonl"))


def test_paired_summary_excludes_incomplete_triplet_without_changing_denominator():
    answers = [
        {
            "case_id": q,
            "repeat": 0,
            "arm": arm,
            "cohort": "primary",
            "status": "answered",
            "elapsed_s": 1.0,
        }
        for q in ("q1", "q2")
        for arm in ARMS
    ]
    judgments = [
        {"case_id": "q1", "repeat": 0, "arm": arm, "status": "judged", "verdict": {"total": score}}
        for arm, score in zip(ARMS, [2, 4, 5], strict=True)
    ]
    judgments.append({"case_id": "q2", "repeat": 0, "arm": ARMS[0], "status": "judge_error"})
    report = paired_summary(answers, judgments)
    cohort = report["paired"]["primary"]
    assert cohort["eligible_triplets"] == 2
    assert cohort["complete_triplets"] == 1
    assert cohort["comparisons"]["predicted_intent-no_intent"]["mean_delta"] == 2
    assert report["judge_status"]["judge_error"] == 1


def test_judge_is_blind_and_keeps_failed_attempts(tmp_path):
    from app.intent_ablation import append_record, judge_prompt, read_jsonl, run_judging

    item = freeze_case(
        {"id": "q", "question": "연차 신청은 언제까지?", "answer": "REFERENCE"},
        "deadline_lookup",
        settings(),
        lambda q: [hit()],
    )
    prompt = judge_prompt(item, "CANDIDATE")
    assert "REFERENCE" in prompt and "CANDIDATE" in prompt
    assert all(arm not in prompt for arm in ARMS)
    answers = tmp_path / "answers.jsonl"
    append_record(
        answers,
        {
            "case_id": "q",
            "repeat": 0,
            "arm": ARMS[0],
            "cohort": "primary",
            "context_sha256": item["context_sha256"],
            "status": "answered",
            "answer": "CANDIDATE",
        },
    )
    calls = []

    def invalid(*args):
        calls.append(args)
        return {"message": {"content": "invalid-json"}}

    output = tmp_path / "judgments.jsonl"
    run_judging([item], answers, output, invalid)
    assert len(calls) == 2
    result = read_jsonl(output)[0]
    assert result["status"] == "judge_error"
    assert len(result["attempts"]) == 2
    run_judging([item], answers, output, invalid)
    assert len(calls) == 2


def test_resume_rejects_different_prompt(tmp_path):
    item = freeze_case(
        {"id": "q", "question": "연차 신청은 언제까지?"},
        "deadline_lookup",
        settings(),
        lambda q: [hit()],
    )

    def call(*args):
        return {"message": {"content": "제39조"}}

    path = tmp_path / "answers.jsonl"
    run_generation([item], path, call, repeats=1)
    item["prompt_sha256"][ARMS[0]] = "changed"
    with pytest.raises(ValueError, match="resume inputs"):
        run_generation([item], path, call, repeats=1)


@pytest.mark.parametrize("name", ["../x", "C:/x", "", "/tmp/x", "x/y", ".."])
def test_report_paths_cannot_escape_local_reports(name):
    from scripts.compare_intent import run_path

    with pytest.raises(ValueError):
        run_path(name)
