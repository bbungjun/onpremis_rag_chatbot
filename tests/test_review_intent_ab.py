import hashlib
import json

import pytest

from scripts import review_intent_ab
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


# ---------------------------------------------------------------------------
# gate CLI: 봉인 검사 -> 기대 명단 생성 -> 판정까지의 전체 경로
# ---------------------------------------------------------------------------
def build_run(tmp_path, monkeypatch, *, repeats=2, contexts=None, reviews=None, history=None):
    """게이트가 읽는 실행 디렉터리를 만든다. 기본값은 통과하는 최소 구성이다."""
    monkeypatch.chdir(tmp_path)
    reports = tmp_path / "reports" / "local-judge"
    reports.mkdir(parents=True)
    artifact = reports / "answers.jsonl"
    artifact.write_text("frozen answers", encoding="utf-8")

    run = tmp_path / "run"
    run.mkdir()
    if contexts is None:
        contexts = [
            {"case": {"id": "c01"}, "prompts": {"no_intent": "질문", "predicted_intent": "지시문"}}
        ]
    write_jsonl(run / "contexts.jsonl", contexts)
    (run / "manifest.json").write_text(
        json.dumps(
            {
                "repeats": repeats,
                "contexts_sha256": sha256_of(run / "contexts.jsonl"),
            }
        ),
        encoding="utf-8",
    )
    (run / "review-metadata.json").write_text(
        json.dumps({"artifact_sha256": {str(artifact): sha256_of(artifact)}}),
        encoding="utf-8",
    )
    if reviews is None:
        reviews = [review("c01", True, False) | {"repeat": r} for r in range(repeats)]
    write_jsonl(run / "boundary-review.jsonl", reviews)
    if history is None:
        history = [review("q11")]
    write_jsonl(run / "historical-review.jsonl", history)

    monkeypatch.setattr(review_intent_ab, "ROOT", tmp_path)
    return run


def write_jsonl(path, rows):
    body = "".join(f"{json.dumps(row, ensure_ascii=False)}\n" for row in rows)
    path.write_text(body, encoding="utf-8")


def sha256_of(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_promotion(run):
    return json.loads((run / "promotion.json").read_text(encoding="utf-8"))


def test_gate_rejects_frozen_contexts_that_no_longer_match_the_manifest(tmp_path, monkeypatch):
    run = build_run(tmp_path, monkeypatch)
    write_jsonl(run / "contexts.jsonl", [])  # 명단을 비워 완전성 검사를 무력화하려는 시도

    with pytest.raises(ValueError, match="frozen context changed"):
        review_intent_ab.main(["gate", "--run", "run"])


def test_gate_fails_when_a_review_file_is_missing_instead_of_reading_it_as_empty(
    tmp_path, monkeypatch
):
    run = build_run(tmp_path, monkeypatch)
    (run / "historical-review.jsonl").unlink()

    with pytest.raises(FileNotFoundError):
        review_intent_ab.main(["gate", "--run", "run"])


def test_gate_fails_when_a_review_file_is_empty(tmp_path, monkeypatch):
    run = build_run(tmp_path, monkeypatch)
    write_jsonl(run / "historical-review.jsonl", [])

    with pytest.raises(ValueError, match="no review records"):
        review_intent_ab.main(["gate", "--run", "run"])


def test_gate_recomputes_input_equal_from_the_frozen_prompts(tmp_path, monkeypatch):
    # 두 arm 의 프롬프트가 같은데 검토자가 "달랐다"고 적은 경우
    contexts = [
        {"case": {"id": "c01"}, "prompts": {"no_intent": "같은 문장", "predicted_intent": "같은 문장"}}
    ]
    build_run(tmp_path, monkeypatch, contexts=contexts)

    with pytest.raises(ValueError, match="input_equal"):
        review_intent_ab.main(["gate", "--run", "run"])


def test_gate_takes_the_repeat_count_from_the_manifest(tmp_path, monkeypatch):
    run = build_run(tmp_path, monkeypatch, repeats=2)
    review_intent_ab.main(["gate", "--run", "run"])

    assert read_promotion(run)["missing_reviews"] == []

    write_jsonl(run / "boundary-review.jsonl", [review("c01", True, False)])  # repeat 0 만 남김
    review_intent_ab.main(["gate", "--run", "run"])
    assert read_promotion(run)["missing_reviews"] == [["c01", 1]]


def test_gate_holds_without_confirmation_and_records_who_confirmed_with_it(tmp_path, monkeypatch):
    run = build_run(tmp_path, monkeypatch)

    review_intent_ab.main(["gate", "--run", "run"])
    held = read_promotion(run)
    assert held["decision"] == "hold"
    assert "representative_independent_confirmation_not_available" in held["reasons"]
    assert held["confirmed_by"] is None

    review_intent_ab.main(["gate", "--run", "run", "--confirmed-by", "held-out-set-2026-09-10"])
    confirmed = read_promotion(run)
    assert confirmed["decision"] == "eligible"
    assert confirmed["confirmed_by"] == "held-out-set-2026-09-10"
