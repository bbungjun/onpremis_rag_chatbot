import json

import pytest

from scripts.review_intent_ab import generate_pairs, promotion_gate


def review(cid, a_pass=True, b_pass=True, a_critical=None, b_critical=None, equal=False):
    return {
        "case_id": cid,
        "repeat": 0,
        "input_equal": equal,
        "A": {"pass": a_pass, "critical": a_critical or []},
        "B": {"pass": b_pass, "critical": b_critical or []},
    }


def test_new_critical_failure_blocks_promotion_even_with_other_wins():
    history = [review("q11", False, True, ["unsupported_denial"])]
    boundary = [review("c01", True, False)]
    result = promotion_gate(history, boundary, {("c01", 0)}, confirmation=True)
    assert result["decision"] == "hold"
    assert result["new_critical_failures"] == [
        {"stage": "historical", "case_id": "q11", "repeat": 0}
    ]


def test_equal_input_wins_and_missing_reviews_cannot_promote():
    result = promotion_gate(
        [], [review("c01", True, False, equal=True)], {("c01", 0), ("c02", 0)}, confirmation=False
    )
    assert result["decision"] == "hold"
    assert result["changed_input_wins"] == 0
    assert result["missing_reviews"] == [["c02", 0]]


def test_only_complete_confirmed_no_regression_result_can_qualify():
    row = review("c01", True, False)
    assert promotion_gate([], [row], {("c01", 0)}, confirmation=False)["decision"] == "hold"
    assert promotion_gate([], [row], {("c01", 0)}, confirmation=True)["decision"] == "eligible"


def test_inconsistent_or_duplicate_reviews_are_rejected():
    with pytest.raises(ValueError):
        promotion_gate([], [review("c01", True, True, ["unsupported_denial"])], {("c01", 0)})
    with pytest.raises(ValueError):
        promotion_gate([], [review("c01"), review("c01")], {("c01", 0)})


def test_pair_generation_uses_two_arms_and_shared_seed_then_resumes(tmp_path):
    item = {
        "case": {"id": "c01"},
        "context_sha256": "context",
        "system_prompt": "system",
        "prompts": {"no_intent": "original", "predicted_intent": "canonical"},
        "parents": [{"text": "policy"}],
    }
    calls = []

    def call(system, user, seed):
        calls.append((system, user, seed))
        return {"message": {"content": "제39조 근거 답변"}, "done_reason": "stop"}

    path = tmp_path / "answers.jsonl"
    generate_pairs([item], path, call, repeats=3)
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 6
    assert {r["arm"] for r in rows} == {"A", "B"}
    for repeat in range(3):
        assert len({r["seed"] for r in rows if r["repeat"] == repeat}) == 1
    assert len({r["seed"] for r in rows}) == 3
    generate_pairs([item], path, call, repeats=3)
    assert len(calls) == 6
