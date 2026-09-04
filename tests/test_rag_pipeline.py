import importlib
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def rag_pipeline():
    try:
        return importlib.import_module("app.rag_pipeline")
    except ModuleNotFoundError as exc:
        pytest.fail(f"app.rag_pipeline should exist: {exc}")


def ask_rag():
    try:
        return importlib.import_module("scripts.ask_rag")
    except ModuleNotFoundError as exc:
        pytest.fail(f"scripts.ask_rag should exist: {exc}")


def make_settings():
    return SimpleNamespace(
        ollama_base_url="http://ollama.test",
        embedding_model="bge-m3",
        qdrant_url="http://qdrant.test",
        qdrant_collection="chunks",
        llm_model="qwen3.6:latest",
        temperature=0.2,
        num_ctx=4096,
        num_predict=512,
    )


def child_hit(score=0.91, *, parent_id="doc:reg::jo-1", parent_text=None, **overrides):
    """검색 결과 1건(child payload)을 만든다. ingest 가 저장하는 형태를 모사."""
    payload = {
        "chunk_id": "doc:reg::jo-1-hang-1",
        "document_id": "doc:reg",
        "source_path": "datasets/docs/regulations.md",
        "title": "사내 규정집",
        "type": "child",
        "parent_id": parent_id,
        "jo": "제1조",
        "path": "제1편 총칙 > 제1장 일반 > 제1절 통칙 > 제1조",
        "hang_no": 1,
        "text": "연차 신청은 최소 3영업일 전까지 해야 한다.",
        "parent_text": parent_text or "제1조 (연차)\n① 연차 신청은 최소 3영업일 전까지 해야 한다.",
    }
    payload.update(overrides)
    return {"score": score, "payload": payload}


@pytest.mark.parametrize("question", ["", "   "])
def test_answer_question_rejects_empty_question(question):
    pipeline = rag_pipeline()

    with pytest.raises(ValueError, match="question"):
        pipeline.answer_question(question, 5, settings=make_settings())


@pytest.mark.parametrize("top_k", [0, -1])
def test_answer_question_rejects_invalid_top_k(top_k):
    pipeline = rag_pipeline()

    with pytest.raises(ValueError, match="top_k"):
        pipeline.answer_question(
            "연차 신청은 며칠 전까지 해야 하나요?", top_k, settings=make_settings()
        )


def test_answer_question_rejects_non_dict_metadata_filter():
    pipeline = rag_pipeline()

    with pytest.raises(TypeError, match="metadata_filter"):
        pipeline.answer_question(
            "연차 신청은 며칠 전까지 해야 하나요?",
            5,
            metadata_filter=["department=hr"],
            settings=make_settings(),
        )


def test_answer_question_falls_back_without_qwen_when_search_returns_no_results(monkeypatch):
    pipeline = rag_pipeline()
    chat_calls = []

    monkeypatch.setattr(pipeline, "embed_text", lambda *args: [0.1, 0.2, 0.3])
    monkeypatch.setattr(pipeline, "search_chunks", lambda *args, **kwargs: [])
    monkeypatch.setattr(pipeline, "chat_qwen", lambda *args, **kwargs: chat_calls.append(args))

    result = pipeline.answer_question(
        "연차 신청은 며칠 전까지 해야 하나요?", 5, settings=make_settings()
    )

    assert result == {"answer": pipeline.FALLBACK_ANSWER, "sources": []}
    assert chat_calls == []


def test_answer_question_falls_back_when_payload_has_no_usable_text(monkeypatch):
    pipeline = rag_pipeline()
    chat_calls = []

    monkeypatch.setattr(pipeline, "embed_text", lambda *args: [0.1, 0.2, 0.3])
    monkeypatch.setattr(
        pipeline,
        "search_chunks",
        lambda *args, **kwargs: [{"score": 0.9, "payload": {"parent_id": "doc:reg::jo-9"}}],
    )
    monkeypatch.setattr(pipeline, "chat_qwen", lambda *args, **kwargs: chat_calls.append(args))

    result = pipeline.answer_question(
        "연차 신청은 며칠 전까지 해야 하나요?", 5, settings=make_settings()
    )

    assert result == {"answer": pipeline.FALLBACK_ANSWER, "sources": []}
    assert chat_calls == []


def test_answer_question_passes_metadata_filter_to_search(monkeypatch):
    pipeline = rag_pipeline()
    captured = {}

    monkeypatch.setattr(pipeline, "embed_text", lambda *args: [0.1, 0.2, 0.3])

    def fake_search_chunks(qdrant_url, collection, dense, sparse, top_k, **kwargs):
        captured["metadata_filter"] = kwargs.get("metadata_filter")
        captured["top_k"] = top_k
        captured["sparse"] = sparse
        return [child_hit()]

    monkeypatch.setattr(pipeline, "search_chunks", fake_search_chunks)
    monkeypatch.setattr(pipeline, "chat_qwen", lambda *args, **kwargs: "답변")

    pipeline.answer_question(
        "연차 신청은 며칠 전까지 해야 하나요?",
        5,
        metadata_filter={"jang": "제2장 휴가", "department": "hr"},
        settings=make_settings(),
    )

    assert captured["metadata_filter"] == {"jang": "제2장 휴가", "department": "hr"}
    assert captured["top_k"] == 5 * pipeline.PARENT_EXPANSION_FETCH_MULTIPLIER
    # 질문도 sparse(BM25) 벡터로 변환돼 함께 넘어간다.
    assert set(captured["sparse"]) == {"indices", "values"}


def test_answer_question_empty_filter_becomes_none(monkeypatch):
    pipeline = rag_pipeline()
    captured = {}

    monkeypatch.setattr(pipeline, "embed_text", lambda *args: [0.1, 0.2, 0.3])

    def fake_search_chunks(qdrant_url, collection, dense, sparse, top_k, **kwargs):
        captured["metadata_filter"] = kwargs.get("metadata_filter")
        return [child_hit()]

    monkeypatch.setattr(pipeline, "search_chunks", fake_search_chunks)
    monkeypatch.setattr(pipeline, "chat_qwen", lambda *args, **kwargs: "답변")

    pipeline.answer_question(
        "연차 신청은 며칠 전까지 해야 하나요?", 5, metadata_filter={}, settings=make_settings()
    )

    assert captured["metadata_filter"] is None


def test_answer_question_expands_to_parent_and_returns_sources(monkeypatch):
    pipeline = rag_pipeline()
    captured = {}

    monkeypatch.setattr(pipeline, "embed_text", lambda *args: [0.1, 0.2, 0.3])
    monkeypatch.setattr(pipeline, "search_chunks", lambda *args, **kwargs: [child_hit()])

    def fake_chat_qwen(
        base_url, model, system_prompt, user_prompt, temperature, num_ctx, num_predict
    ):
        captured["system_prompt"] = system_prompt
        captured["user_prompt"] = user_prompt
        captured["base_url"] = base_url
        captured["model"] = model
        return "연차 신청은 최소 3영업일 전까지 해야 합니다. (제1조)"

    monkeypatch.setattr(pipeline, "chat_qwen", fake_chat_qwen)

    result = pipeline.answer_question(
        "연차 신청은 며칠 전까지 해야 하나요?", 5, settings=make_settings()
    )

    assert result == {
        "answer": "연차 신청은 최소 3영업일 전까지 해야 합니다. (제1조)",
        "sources": [
            {
                "source_path": "datasets/docs/regulations.md",
                "chunk_id": "doc:reg::jo-1",
                "score": 0.91,
            }
        ],
    }
    assert captured["base_url"] == "http://ollama.test"
    assert captured["model"] == "qwen3.6:latest"
    # parent(조) 전체 본문이 context 로 전달된다 (parent 확장).
    assert "제1조 (연차)" in captured["user_prompt"]
    assert "doc:reg::jo-1" in captured["user_prompt"]
    assert "\npath:" not in captured["user_prompt"]
    assert "\nscore:" not in captured["user_prompt"]
    assert "문서에서 확인되지 않습니다" in captured["system_prompt"]


def test_answer_question_passes_original_and_canonical_question_to_qwen(monkeypatch):
    pipeline = rag_pipeline()
    captured = {}

    monkeypatch.setattr(pipeline, "embed_text", lambda *args: [0.1, 0.2, 0.3])
    monkeypatch.setattr(pipeline, "search_chunks", lambda *args, **kwargs: [child_hit()])

    def fake_chat_qwen(
        base_url, model, system_prompt, user_prompt, temperature, num_ctx, num_predict
    ):
        captured["user_prompt"] = user_prompt
        return "문서 기준상 최소 3영업일 전까지 신청해야 하므로 2일 뒤는 기준을 충족하지 않습니다."

    monkeypatch.setattr(pipeline, "chat_qwen", fake_chat_qwen)

    pipeline.answer_question("2일 뒤에 연차 신청하려고 하는데 될까요?", 5, settings=make_settings())

    assert "[original_question]" in captured["user_prompt"]
    assert "2일 뒤에 연차 신청하려고 하는데 될까요?" in captured["user_prompt"]
    assert "[canonical_question]" in captured["user_prompt"]
    assert "문서 기준상" in captured["user_prompt"]
    assert "충족" in captured["user_prompt"]


def test_answer_question_passes_structural_leave_canonical_question(monkeypatch):
    pipeline = rag_pipeline()
    captured = {}

    monkeypatch.setattr(pipeline, "embed_text", lambda *args: [0.1, 0.2, 0.3])
    monkeypatch.setattr(pipeline, "search_chunks", lambda *args, **kwargs: [child_hit()])

    def fake_chat_qwen(
        base_url, model, system_prompt, user_prompt, temperature, num_ctx, num_predict
    ):
        captured["user_prompt"] = user_prompt
        captured["model"] = model
        return "문서 기준상 3영업일 이상 남는다면 연차 신청이 가능합니다."

    settings = make_settings()
    settings.llm_model = "exaone3.5:7.8b"
    monkeypatch.setattr(pipeline, "chat_qwen", fake_chat_qwen)

    result = pipeline.answer_question(
        "4일뒤에 연차 신청하려고 하는데 가능할까요?",
        5,
        settings=settings,
    )

    assert result["answer"] == "문서 기준상 3영업일 이상 남는다면 연차 신청이 가능합니다."
    assert captured["model"] == "exaone3.5:7.8b"
    assert "[canonical_question]" in captured["user_prompt"]
    assert "연차를 4일 뒤에 사용" in captured["user_prompt"]
    assert "사용자 조건이 M 이상이면 기준을 충족" in captured["user_prompt"]


def test_answer_question_returns_llm_answer_unchanged_for_any_model(monkeypatch):
    """모델이나 질문 유형에 따라 LLM 답변을 규칙으로 덮어쓰지 않는다."""
    pipeline = rag_pipeline()
    raw_answer = (
        "문서에 따르면 연차 신청은 최소 3영업일 전까지 해야 하므로 "
        "4일 뒤라면 연차 신청이 불가능합니다."
    )

    monkeypatch.setattr(pipeline, "embed_text", lambda *args: [0.1, 0.2, 0.3])
    monkeypatch.setattr(pipeline, "search_chunks", lambda *args, **kwargs: [child_hit()])
    monkeypatch.setattr(pipeline, "chat_qwen", lambda *args, **kwargs: raw_answer)

    for model in ("exaone3.5:7.8b", "qwen3:4b-instruct"):
        settings = make_settings()
        settings.llm_model = model

        result = pipeline.answer_question(
            "4일뒤에 연차 신청하려고 하는데 가능할까요?",
            5,
            settings=settings,
        )

        assert result["answer"] == raw_answer, model


def test_answer_question_keeps_original_question_for_general_retrieval(monkeypatch):
    pipeline = rag_pipeline()
    captured = {}

    def fake_embed_text(base_url, model, text):
        captured["embedded_text"] = text
        return [0.1, 0.2, 0.3]

    monkeypatch.setattr(pipeline, "embed_text", fake_embed_text)
    monkeypatch.setattr(pipeline, "search_chunks", lambda *args, **kwargs: [child_hit()])
    monkeypatch.setattr(pipeline, "chat_qwen", lambda *args, **kwargs: "답변")

    pipeline.answer_question("회사의 휴가 규정을 알려주세요.", 5, settings=make_settings())

    assert captured["embedded_text"] == "회사의 휴가 규정을 알려주세요."


def test_answer_question_uses_lightly_normalized_retrieval_question(monkeypatch):
    pipeline = rag_pipeline()
    captured = {}

    def fake_embed_text(base_url, model, text):
        captured["embedded_text"] = text
        return [0.1, 0.2, 0.3]

    def fake_text_to_sparse(text):
        captured["sparse_text"] = text
        return {"indices": [1], "values": [1.0]}

    monkeypatch.setattr(pipeline, "embed_text", fake_embed_text)
    monkeypatch.setattr(pipeline, "text_to_sparse", fake_text_to_sparse)
    monkeypatch.setattr(pipeline, "search_chunks", lambda *args, **kwargs: [child_hit()])
    monkeypatch.setattr(pipeline, "chat_qwen", lambda *args, **kwargs: "답변")

    pipeline.answer_question("이틀 뒤에 연차신청해도될까요?", 5, settings=make_settings())

    assert captured["embedded_text"] == "연차 유급휴가 신청 기한 최소 영업일 전"
    assert captured["sparse_text"] == "연차 유급휴가 신청 기한 최소 영업일 전"


def test_system_prompt_instructs_qwen_to_use_canonical_question():
    pipeline = rag_pipeline()

    assert "canonical_question" in pipeline.SYSTEM_PROMPT
    assert "original_question" in pipeline.SYSTEM_PROMPT
    assert "문서에 없는 승인 재량" in pipeline.SYSTEM_PROMPT
    assert "새 달력 날짜" in pipeline.SYSTEM_PROMPT
    assert "문서 기준상 충족하지 않습니다" in pipeline.SYSTEM_PROMPT


def test_answer_question_dedupes_children_sharing_a_parent(monkeypatch):
    pipeline = rag_pipeline()

    monkeypatch.setattr(pipeline, "embed_text", lambda *args: [0.1, 0.2, 0.3])
    monkeypatch.setattr(
        pipeline,
        "search_chunks",
        lambda *args, **kwargs: [
            child_hit(score=0.95, parent_id="doc:reg::jo-1"),
            child_hit(score=0.80, parent_id="doc:reg::jo-1"),
            child_hit(
                score=0.70,
                parent_id="doc:reg::jo-2",
                parent_text="제2조 (재택근무)\n① 재택근무는 승인이 필요하다.",
                jo="제2조",
            ),
        ],
    )
    monkeypatch.setattr(pipeline, "chat_qwen", lambda *args, **kwargs: "답변")

    result = pipeline.answer_question("질문", 5, settings=make_settings())

    # 같은 조(jo-1)는 한 번만, 최고 점수로 출처에 남는다.
    assert result["sources"] == [
        {"source_path": "datasets/docs/regulations.md", "chunk_id": "doc:reg::jo-1", "score": 0.95},
        {"source_path": "datasets/docs/regulations.md", "chunk_id": "doc:reg::jo-2", "score": 0.70},
    ]


def test_build_context_trims_low_score_parents_to_fit_prompt_budget():
    pipeline = rag_pipeline()
    long_text = "문서 내용 " * 80
    search_results = [
        child_hit(
            score=1.0 - (index * 0.1),
            parent_id=f"doc:reg::jo-{index}",
            parent_text=f"제{index}조\n{long_text}",
            jo=f"제{index}조",
        )
        for index in range(1, 6)
    ]

    parents, user_prompt = pipeline._build_context(
        "재택근무 승인 절차는 어떻게 되나요?",
        search_results,
        5,
        max_prompt_chars=900,
    )

    assert len(user_prompt) <= 900
    assert len(parents) < 5
    assert parents[0].chunk_id == "doc:reg::jo-1"
    assert "doc:reg::jo-5" not in user_prompt


def test_answer_question_overfetches_children_before_parent_deduping(monkeypatch):
    pipeline = rag_pipeline()
    captured = {}

    monkeypatch.setattr(pipeline, "embed_text", lambda *args: [0.1, 0.2, 0.3])

    def fake_search_chunks(qdrant_url, collection, dense, sparse, top_k, **kwargs):
        captured["search_top_k"] = top_k
        return [
            child_hit(score=0.95, parent_id="doc:reg::jo-1"),
            child_hit(score=0.91, parent_id="doc:reg::jo-1"),
            child_hit(score=0.88, parent_id="doc:reg::jo-1"),
            child_hit(
                score=0.70,
                parent_id="doc:reg::jo-2",
                parent_text="제2조 (재택근무)\n① 재택근무는 승인이 필요하다.",
                jo="제2조",
            ),
            child_hit(
                score=0.60,
                parent_id="doc:reg::jo-3",
                parent_text="제3조 (출장)\n① 출장 정산은 기한 내 처리한다.",
                jo="제3조",
            ),
        ]

    monkeypatch.setattr(pipeline, "search_chunks", fake_search_chunks)
    monkeypatch.setattr(pipeline, "chat_qwen", lambda *args, **kwargs: "답변")

    result = pipeline.answer_question("질문", 2, settings=make_settings())

    assert captured["search_top_k"] == pipeline._search_top_k_for_parent_expansion(2)
    assert result["sources"] == [
        {"source_path": "datasets/docs/regulations.md", "chunk_id": "doc:reg::jo-1", "score": 0.95},
        {"source_path": "datasets/docs/regulations.md", "chunk_id": "doc:reg::jo-2", "score": 0.70},
    ]


def test_answer_question_reports_four_stage_progress(monkeypatch):
    pipeline = rag_pipeline()
    progress_events = []

    monkeypatch.setattr(pipeline, "embed_text", lambda *args: [0.1, 0.2, 0.3])
    monkeypatch.setattr(pipeline, "search_chunks", lambda *args, **kwargs: [child_hit()])
    monkeypatch.setattr(pipeline, "chat_qwen", lambda *args, **kwargs: "답변")

    pipeline.answer_question(
        "연차 신청은 며칠 전까지 해야 하나요?",
        5,
        settings=make_settings(),
        progress=progress_events.append,
    )

    assert progress_events == [
        "[1/4] Embedding question...",
        "[2/4] Searching Qdrant (metadata filter)...",
        "[3/4] Expanding to parent articles...",
        "[4/4] Generating answer with Qwen...",
    ]


def test_answer_question_reports_timing_events_on_grounded_path(monkeypatch):
    pipeline = rag_pipeline()
    timing_events = []
    clock_values = iter([0.00, 0.35, 0.35, 0.36, 0.36, 0.44, 0.44, 0.45, 0.45, 2.45])

    monkeypatch.setattr(pipeline, "perf_counter", lambda: next(clock_values), raising=False)
    monkeypatch.setattr(pipeline, "embed_text", lambda *args: [0.1, 0.2, 0.3])
    monkeypatch.setattr(pipeline, "search_chunks", lambda *args, **kwargs: [child_hit()])
    monkeypatch.setattr(pipeline, "chat_qwen", lambda *args, **kwargs: "답변")

    pipeline.answer_question(
        "연차 신청은 며칠 전까지 해야 하나요?",
        5,
        settings=make_settings(),
        timing=lambda label, seconds: timing_events.append((label, seconds)),
    )

    assert [event[0] for event in timing_events] == [
        "Embedding question",
        "Sparse vector",
        "Qdrant search",
        "Parent expansion",
        "Qwen generation",
    ]
    assert [event[1] for event in timing_events] == pytest.approx([0.35, 0.01, 0.08, 0.01, 2.00])


def test_answer_question_reports_only_completed_timing_on_search_fallback(monkeypatch):
    pipeline = rag_pipeline()
    timing_events = []
    clock_values = iter([1.00, 1.05, 1.05, 1.06, 1.06, 1.09])

    monkeypatch.setattr(pipeline, "perf_counter", lambda: next(clock_values), raising=False)
    monkeypatch.setattr(pipeline, "embed_text", lambda *args: [0.1, 0.2, 0.3])
    monkeypatch.setattr(pipeline, "search_chunks", lambda *args, **kwargs: [])
    monkeypatch.setattr(pipeline, "chat_qwen", lambda *args, **kwargs: "답변")

    result = pipeline.answer_question(
        "연차 신청은 며칠 전까지 해야 하나요?",
        5,
        settings=make_settings(),
        timing=lambda label, seconds: timing_events.append((label, seconds)),
    )

    assert result == {"answer": pipeline.FALLBACK_ANSWER, "sources": []}
    assert [event[0] for event in timing_events] == [
        "Embedding question",
        "Sparse vector",
        "Qdrant search",
    ]


def test_ask_rag_cli_prints_answer_and_sources(monkeypatch, capsys):
    cli = ask_rag()

    monkeypatch.setattr(
        cli,
        "answer_question",
        lambda *args, **kwargs: {
            "answer": "연차 신청은 최소 3영업일 전까지 해야 합니다.",
            "sources": [
                {
                    "source_path": "datasets/docs/regulations.md",
                    "chunk_id": "doc:reg::jo-1",
                    "score": 0.91,
                }
            ],
        },
    )

    exit_code = cli.main(["연차 신청은 며칠 전까지 해야 하나요?", "--top-k", "5"])

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "Answer:" in output
    assert "연차 신청은 최소 3영업일 전까지 해야 합니다." in output
    assert "Sources:" in output
    assert "- datasets/docs/regulations.md#doc:reg::jo-1 (score: 0.91)" in output


def test_ask_rag_cli_parses_filter_pairs_into_metadata_filter(monkeypatch):
    cli = ask_rag()
    captured = {}

    def fake_answer_question(question, top_k, **kwargs):
        captured["question"] = question
        captured["top_k"] = top_k
        captured["metadata_filter"] = kwargs.get("metadata_filter")
        return {"answer": "답변", "sources": []}

    monkeypatch.setattr(cli, "answer_question", fake_answer_question)

    exit_code = cli.main(
        [
            "연차 규정 알려줘",
            "--filter",
            "jang=제2장 휴가",
            "--filter",
            "department=hr",
        ]
    )

    assert exit_code == 0
    assert captured["metadata_filter"] == {"jang": "제2장 휴가", "department": "hr"}


def test_ask_rag_cli_preserves_explicit_zero_top_k(monkeypatch):
    cli = ask_rag()
    captured = {}

    def fake_answer_question(question, top_k, **kwargs):
        captured["top_k"] = top_k
        return {"answer": "답변", "sources": []}

    monkeypatch.setattr(cli, "answer_question", fake_answer_question)

    exit_code = cli.main(["질문", "--top-k", "0"])

    assert exit_code == 0
    assert captured["top_k"] == 0


def test_ask_rag_cli_rejects_malformed_filter(monkeypatch):
    cli = ask_rag()
    monkeypatch.setattr(
        cli, "answer_question", lambda *args, **kwargs: {"answer": "", "sources": []}
    )

    with pytest.raises(ValueError, match="KEY=VALUE"):
        cli.main(["질문", "--filter", "broken"])


def test_ask_rag_cli_prints_progress_to_stderr(monkeypatch, capsys):
    cli = ask_rag()

    def fake_answer_question(*args, **kwargs):
        kwargs["progress"]("[1/4] Embedding question...")
        kwargs["progress"]("[4/4] Generating answer with Qwen...")
        return {"answer": "연차 신청은 최소 3영업일 전까지 해야 합니다.", "sources": []}

    monkeypatch.setattr(cli, "answer_question", fake_answer_question)

    exit_code = cli.main(["연차 신청은 며칠 전까지 해야 하나요?"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "[1/4] Embedding question..." in captured.err
    assert "[4/4] Generating answer with Qwen..." in captured.err
    assert "[1/4] Embedding question..." not in captured.out
    assert "Answer:" in captured.out
    assert "Sources:" in captured.out


def test_ask_rag_cli_prints_timing_to_stderr_when_requested(monkeypatch, capsys):
    cli = ask_rag()
    captured_kwargs = {}

    def fake_answer_question(*args, **kwargs):
        captured_kwargs.update(kwargs)
        kwargs["timing"]("Qwen generation", 1.23456)
        return {"answer": "The policy confirms the required action.", "sources": []}

    monkeypatch.setattr(cli, "answer_question", fake_answer_question)

    exit_code = cli.main(["How should annual leave be requested?", "--timing"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert callable(captured_kwargs["timing"])
    assert "[timing] Qwen generation: 1.235s" in captured.err
    assert "[timing]" not in captured.out
    assert "Answer:" in captured.out


def test_ask_rag_cli_omits_timing_callback_by_default(monkeypatch):
    cli = ask_rag()
    captured_kwargs = {}

    def fake_answer_question(*args, **kwargs):
        captured_kwargs.update(kwargs)
        return {"answer": "The policy confirms the required action.", "sources": []}

    monkeypatch.setattr(cli, "answer_question", fake_answer_question)

    exit_code = cli.main(["How should annual leave be requested?"])

    assert exit_code == 0
    assert captured_kwargs["timing"] is None
