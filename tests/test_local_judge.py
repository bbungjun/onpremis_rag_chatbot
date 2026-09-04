from __future__ import annotations

import pytest

from app import local_judge as judge


def test_parse_judge_verdict_returns_score_total_for_valid_json():
    verdict = judge.parse_judge_verdict(
        '{"correctness": 2, "groundedness": 1, "completeness": 2, '
        '"rationale": "근거 조항과 일치합니다."}'
    )

    assert verdict.correctness == 2
    assert verdict.groundedness == 1
    assert verdict.completeness == 2
    assert verdict.total == 5
    assert verdict.rationale == "근거 조항과 일치합니다."


def test_parse_judge_verdict_accepts_exaone_json_markdown_fence():
    payload = """```json
{"correctness": 2, "groundedness": 2, "completeness": 1, "rationale": "일치"}
```"""

    verdict = judge.parse_judge_verdict(payload)

    assert verdict.total == 5


def test_parse_judge_verdict_accepts_exaone_literal_newline_in_rationale():
    payload = """```json
{"correctness": 2, "groundedness": 2, "completeness": 1,
 "rationale": "첫 문장
둘째 문장"}
```"""

    verdict = judge.parse_judge_verdict(payload)

    assert verdict.rationale == "첫 문장\n둘째 문장"


def test_parse_judge_verdict_accepts_exaone_backslash_before_newline():
    payload = (
        "```json\n"
        '{"correctness": 2, "groundedness": 2, "completeness": 1, '
        '"rationale": "첫 문장\\\n둘째 문장"}\n'
        "```"
    )

    verdict = judge.parse_judge_verdict(payload)

    assert verdict.rationale == "첫 문장\n둘째 문장"


@pytest.mark.parametrize(
    "payload",
    [
        "not-json",
        "[]",
        '{"correctness": 2, "groundedness": 1, "completeness": 2, '
        '"rationale": "추가 필드", "extra": true}',
        '{"correctness": -1, "groundedness": 1, "completeness": 2, "rationale": "범위 미만"}',
        '{"correctness": 1.0, "groundedness": 1, "completeness": 2, "rationale": "실수 점수"}',
        '{"correctness": 3, "groundedness": 1, "completeness": 2, "rationale": "범위 초과"}',
        '{"correctness": true, "groundedness": 1, "completeness": 2, "rationale": "불리언"}',
        '{"correctness": 2, "groundedness": 1, "completeness": 2, "rationale": ""}',
        '{"correctness": 2, "groundedness": 1, "rationale": "필드 누락"}',
    ],
)
def test_parse_judge_verdict_rejects_invalid_score_or_shape(payload: str):
    with pytest.raises(ValueError):
        judge.parse_judge_verdict(payload)


def test_judge_answer_returns_validated_verdict_from_separate_local_model():
    captured: dict[str, object] = {}

    def fake_chat(
        base_url: str,
        model: str,
        system_prompt: str,
        user_prompt: str,
        temperature: float,
        num_ctx: int,
        num_predict: int,
    ) -> str:
        captured.update(
            {
                "base_url": base_url,
                "model": model,
                "system_prompt": system_prompt,
                "user_prompt": user_prompt,
                "temperature": temperature,
                "num_ctx": num_ctx,
                "num_predict": num_predict,
            }
        )
        return (
            '{"correctness": 2, "groundedness": 2, "completeness": 2, '
            '"rationale": "정답과 근거가 일치합니다."}'
        )

    verdict = judge.judge_answer(
        base_url="http://ollama.local",
        judge_model="exaone3.5:7.8b",
        question="연차 신청은 언제까지 해야 하나요?",
        reference_answer="최소 3영업일 전 사내 그룹웨어로 신청해야 합니다.",
        candidate_answer="최소 3영업일 전 그룹웨어로 신청하세요.",
        source_ids=["doc:reg::jo-39"],
        num_ctx=4096,
        chat=fake_chat,
    )

    assert verdict.total == 6
    assert captured["model"] == "exaone3.5:7.8b"
    assert captured["temperature"] == 0.0
    assert captured["num_ctx"] == 4096
    assert captured["num_predict"] == 256
    assert "최소 3영업일 전 그룹웨어로 신청하세요." in str(captured["user_prompt"])
    assert "doc:reg::jo-39" in str(captured["user_prompt"])
    assert "최소 3영업일 전 그룹웨어로 신청하세요." not in str(captured["system_prompt"])


def test_judge_answer_retries_one_malformed_local_model_response():
    responses = iter(
        [
            "not-json",
            '{"correctness": 2, "groundedness": 2, "completeness": 2, "rationale": "재시도 성공"}',
        ]
    )

    verdict = judge.judge_answer(
        base_url="http://ollama.local",
        judge_model="exaone3.5:7.8b",
        question="질문",
        reference_answer="정답",
        candidate_answer="답변",
        source_ids=["jo-1"],
        num_ctx=4096,
        chat=lambda *args: next(responses),
    )

    assert verdict.total == 6


def test_judge_answer_rejects_qwen_as_judge_model():
    with pytest.raises(ValueError, match="supported local judge"):
        judge.judge_answer(
            base_url="http://ollama.local",
            judge_model="qwen3:4b-instruct",
            question="연차 신청은 언제까지 해야 하나요?",
            reference_answer="최소 3영업일 전 신청해야 합니다.",
            candidate_answer="최소 3영업일 전 신청해야 합니다.",
            source_ids=["doc:reg::jo-39"],
            num_ctx=4096,
            chat=lambda *args: (
                '{"correctness": 2, "groundedness": 2, "completeness": 2, "rationale": "일치"}'
            ),
        )


@pytest.mark.parametrize(
    "judge_model",
    [
        "hf.co/Qwen/Qwen3-8B",
        "registry.local/team/qwen2.5:7b",
        "custom-local-alias",
    ],
)
def test_judge_answer_rejects_models_outside_the_controlled_judge_allowlist(judge_model: str):
    with pytest.raises(ValueError, match="supported local judge"):
        judge.judge_answer(
            base_url="http://ollama.local",
            judge_model=judge_model,
            question="연차 신청은 언제까지 해야 하나요?",
            reference_answer="최소 3영업일 전 신청해야 합니다.",
            candidate_answer="최소 3영업일 전 신청해야 합니다.",
            source_ids=["doc:reg::jo-39"],
            num_ctx=4096,
            chat=lambda *args: (
                '{"correctness": 2, "groundedness": 2, "completeness": 2, "rationale": "일치"}'
            ),
        )
