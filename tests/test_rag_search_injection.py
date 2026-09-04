from types import SimpleNamespace

from app import rag_pipeline


def test_answer_question_uses_injected_retrieval_and_returns_its_parent_source(monkeypatch):
    # Given
    captured = {}
    settings = SimpleNamespace(
        ollama_base_url="http://ollama.test",
        embedding_model="bge-m3",
        qdrant_url="http://qdrant.test",
        qdrant_collection="chunks",
        llm_model="qwen3.6:latest",
        temperature=0.2,
        num_ctx=4096,
        num_predict=512,
    )
    monkeypatch.setattr(rag_pipeline, "embed_text", lambda *args: [0.1])
    monkeypatch.setattr(rag_pipeline, "chat_qwen", lambda *args: "근거 답변")

    def injected(question, dense, sparse, top_k, metadata_filter, active_settings):
        captured.update(
            question=question,
            dense=dense,
            sparse=sparse,
            top_k=top_k,
            metadata_filter=metadata_filter,
            settings=active_settings,
        )
        return [
            {
                "score": 0.95,
                "payload": {
                    "chunk_id": "jo-7-hang-1",
                    "parent_id": "jo-7",
                    "source_path": "datasets/docs/regulations.md",
                    "title": "사내 규정집",
                    "jo": "제7조",
                    "path": "제7조",
                    "text": "child",
                    "parent_text": "제7조 근거",
                },
            }
        ]

    # When
    result = rag_pipeline.answer_question(
        "출장비는 언제까지 정산하나요?",
        5,
        settings=settings,
        retrieval_search=injected,
    )

    # Then
    assert captured["question"] == "출장비는 언제까지 정산하나요?"
    assert captured["top_k"] == 20
    assert captured["settings"] is settings
    assert result["sources"] == [
        {
            "source_path": "datasets/docs/regulations.md",
            "chunk_id": "jo-7",
            "score": 0.95,
        }
    ]
