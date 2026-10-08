from types import SimpleNamespace

import pytest

from scripts.compare_local_models import (
    capture_case,
    make_request,
    summarize_generation,
    validate_pairs,
)


def test_capture_keeps_original_sources_and_separate_prompts():
    def answer(question, top_k, *, settings, llm):
        assert question == "연차 신청 기한은?"
        llm.generate("system", "retrieved data")
        return {"answer": "captured", "sources": [{"chunk_id": "jo-1"}]}

    frozen = capture_case(
        {"id": "a", "question": "연차 신청 기한은?"},
        settings=SimpleNamespace(retrieval_top_k=5),
        answer=answer,
    )
    assert frozen["system_prompt"] == "system"
    assert frozen["user_prompt"] == "retrieved data"
    assert frozen["sources"] == [{"chunk_id": "jo-1"}]
    assert len(frozen["prompt_sha256"]) == 64


def test_empty_retrieval_is_not_silently_compared_as_model_generation():
    with pytest.raises(ValueError, match="generation"):
        capture_case(
            {"id": "a", "question": "연차 신청 기한은?"},
            settings=SimpleNamespace(retrieval_top_k=5),
            answer=lambda *args, **kwargs: {"answer": "fallback", "sources": []},
        )


def test_model_requests_share_messages_and_options_without_mutation():
    frozen = {"system_prompt": "system", "user_prompt": "data"}
    options = {"num_ctx": 4096, "seed": 42}
    first = make_request(frozen, "qwen3:4b-instruct", options)
    second = make_request(frozen, "exaone3.5:7.8b", options)
    assert first["messages"] == second["messages"]
    assert first["options"] == second["options"] == options
    assert "untrusted" in first["messages"][0]["content"]
    assert frozen["system_prompt"] == "system"


def test_summary_preserves_errors_empty_answers_and_length_termination():
    rows = [
        {"status": "answered", "elapsed_ms": 1000, "done_reason": "stop"},
        {"status": "answered", "elapsed_ms": 3000, "done_reason": "length"},
        {"status": "empty_answer", "elapsed_ms": 4000},
        {"status": "answer_error", "elapsed_ms": 5000},
    ]
    summary = summarize_generation(rows)
    assert summary["total"] == 4
    assert summary["answered"] == 2
    assert summary["errors"] == 2
    assert summary["length_stops"] == 1
    assert summary["answered_mean_ms"] == 2000


def test_two_equally_incomplete_runs_are_not_a_complete_comparison():
    frozen = [{"case": {"id": "a"}, "prompt_sha256": "a", "sources": []}]
    with pytest.raises(ValueError, match="Incomplete"):
        validate_pairs(frozen, [], [])


def test_pairing_rejects_changed_sources_even_if_hash_matches():
    frozen = [{"case": {"id": "a"}, "prompt_sha256": "a", "sources": [{"chunk_id": "jo-1"}]}]
    record = {"case": {"id": "a"}, "prompt_sha256": "a", "source_ids": ["jo-2"]}
    with pytest.raises(ValueError, match="paired"):
        validate_pairs(frozen, [record], [record])
