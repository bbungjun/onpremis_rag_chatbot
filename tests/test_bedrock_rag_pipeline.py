from types import SimpleNamespace

import pytest

from app.bedrock_rag_pipeline import answer_question_with_bedrock


def make_settings():
    return SimpleNamespace(
        ollama_base_url="http://ollama.test",
        embedding_model="bge-m3",
        qdrant_url="http://qdrant.test",
        qdrant_collection="chunks",
        temperature=0.2,
        retrieval_top_k=5,
        num_ctx=4096,
    )


def child_hit(score=0.91):
    return {
        "score": score,
        "payload": {
            "chunk_id": "chunk-leave-1",
            "parent_id": "doc:leave::jo-39",
            "source_path": "datasets/docs/hr/leave-policy.md",
            "title": "leave policy",
            "jo": "Article 39",
            "path": "HR > Leave > Article 39",
            "text": "Annual leave requests must be submitted at least 3 business days ahead.",
            "parent_text": (
                "Article 39 Annual Leave\n"
                "Annual leave requests must be submitted at least 3 business days ahead."
            ),
        },
    }


def test_answer_question_with_bedrock_returns_grounded_answer(monkeypatch):
    import app.bedrock_rag_pipeline as pipeline
    import app.rag_pipeline as retrieval

    settings = make_settings()
    captured = {}

    # 검색·문맥 조립은 rag_pipeline 이 담당한다. bedrock 모듈은 생성기만 갈아끼운다.
    monkeypatch.setattr(retrieval, "embed_text", lambda *args: [0.1, 0.2, 0.3])
    monkeypatch.setattr(retrieval, "text_to_sparse", lambda text: {"indices": [1], "values": [1.0]})

    def fake_search_chunks(*args, **kwargs):
        captured["search_args"] = args
        captured["metadata_filter"] = kwargs.get("metadata_filter")
        return [child_hit()]

    monkeypatch.setattr(retrieval, "search_chunks", fake_search_chunks)

    def fake_chat_bedrock(*args, **kwargs):
        captured["chat_args"] = args
        captured["chat_kwargs"] = kwargs
        return "Annual leave must be requested at least 3 business days ahead."

    monkeypatch.setattr(pipeline, "chat_bedrock", fake_chat_bedrock)

    result = answer_question_with_bedrock(
        "How early should I request annual leave?",
        3,
        metadata_filter={"department": "hr", "category": "leave"},
        region="ap-northeast-2",
        model_id="bedrock-model",
        max_output_tokens=256,
        settings=settings,
    )

    assert result["answer"] == "Annual leave must be requested at least 3 business days ahead."
    assert result["sources"] == [
        {
            "source_path": "datasets/docs/hr/leave-policy.md",
            "chunk_id": "doc:leave::jo-39",
            "score": 0.91,
        }
    ]
    assert captured["metadata_filter"] == {"department": "hr", "category": "leave"}
    assert captured["search_args"][4] == retrieval._search_top_k_for_parent_expansion(3)
    assert captured["chat_args"][0] == "ap-northeast-2"
    assert captured["chat_args"][1] == "bedrock-model"
    assert "doc:leave::jo-39" in captured["chat_args"][3]
    assert "Annual leave requests must be submitted" in captured["chat_args"][3]


def test_answer_question_with_bedrock_falls_back_without_search_results(monkeypatch):
    import app.bedrock_rag_pipeline as pipeline
    import app.rag_pipeline as retrieval

    calls = {"embed": 0, "search": 0, "chat": 0}

    def fake_embed(*args):
        calls["embed"] += 1
        return [0.1, 0.2, 0.3]

    def fake_search(*args, **kwargs):
        calls["search"] += 1
        return []

    monkeypatch.setattr(retrieval, "embed_text", fake_embed)
    monkeypatch.setattr(retrieval, "text_to_sparse", lambda text: {"indices": [1], "values": [1.0]})
    monkeypatch.setattr(retrieval, "search_chunks", fake_search)
    monkeypatch.setattr(
        pipeline,
        "chat_bedrock",
        lambda *args, **kwargs: calls.__setitem__("chat", calls["chat"] + 1),
    )

    result = answer_question_with_bedrock(
        "How early should I request annual leave?",
        3,
        metadata_filter={"department": "finance"},
        region="ap-northeast-2",
        model_id="bedrock-model",
        max_output_tokens=256,
        settings=make_settings(),
    )

    assert result == retrieval._fallback_result()
    assert calls == {"embed": 1, "search": 1, "chat": 0}


@pytest.mark.parametrize("question", ["", "   "])
def test_answer_question_with_bedrock_rejects_empty_question(question):
    with pytest.raises(ValueError, match="question"):
        answer_question_with_bedrock(
            question,
            3,
            region="ap-northeast-2",
            model_id="bedrock-model",
            max_output_tokens=256,
            settings=make_settings(),
        )


def test_answer_question_with_bedrock_rejects_non_dict_metadata_filter():
    with pytest.raises(TypeError, match="metadata_filter"):
        answer_question_with_bedrock(
            "How early should I request annual leave?",
            3,
            metadata_filter=["department=hr"],
            region="ap-northeast-2",
            model_id="bedrock-model",
            max_output_tokens=256,
            settings=make_settings(),
        )
