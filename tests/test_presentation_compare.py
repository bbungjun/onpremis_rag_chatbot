from types import SimpleNamespace

from app.presentation_compare import compare_question


def settings():
    return SimpleNamespace(retrieval_top_k=3, num_predict=192, llm_model="qwen3:4b-instruct")


def answer():
    return {
        "answer": "연차는 3영업일 전까지 신청해야 합니다.",
        "sources": [{"source_path": "a.md", "chunk_id": "chunk-a", "score": 0.9}],
    }


def test_compare_question_uses_existing_gemini_path():
    seen = {}

    def gemini_answer(*args, **kwargs):
        seen.update(kwargs)
        return answer()

    result = compare_question(
        "연차 신청은 며칠 전까지 해야 하나요?",
        {"department": "hr", "category": "leave"},
        settings=settings(),
        gemini_project="demo-project",
        gemini_location="us-central1",
        gemini_model="gemini-2.5-flash",
        local_answer=lambda *args, **kwargs: answer(),
        gemini_answer=gemini_answer,
    )

    assert set(result) == {"question", "filters", "local", "api", "shared_sources"}
    assert result["local"]["status"] == "ok"
    assert result["api"]["label"] == "Vertex Gemini"
    assert result["api"]["model"] == "gemini-2.5-flash"
    assert result["shared_sources"] == answer()["sources"]
    assert seen["project"] == "demo-project"
    assert seen["location"] == "us-central1"
    assert seen["model"] == "gemini-2.5-flash"
    assert seen["max_output_tokens"] == 192


def test_compare_question_uses_selected_local_model():
    base_settings = settings()
    seen_models = []

    def local_answer(*args, **kwargs):
        seen_models.append(kwargs["settings"].llm_model)
        return answer()

    result = compare_question(
        "재택근무 승인 절차는 어떻게 되나요?",
        {},
        settings=base_settings,
        gemini_project="",
        gemini_location="us-central1",
        gemini_model="gemini-2.5-flash",
        local_model="exaone3.5:7.8b",
        local_answer=local_answer,
        gemini_answer=lambda *args, **kwargs: {},
    )

    assert seen_models == ["exaone3.5:7.8b"]
    assert result["local"]["model"] == "exaone3.5:7.8b"
    assert base_settings.llm_model == "qwen3:4b-instruct"
    assert result["api"]["status"] == "pending"
    assert result["api"]["answer"] == "Gemini project가 아직 설정되지 않았습니다."


def test_compare_question_preserves_partial_gemini_failure():
    def failed_gemini(*args, **kwargs):
        raise RuntimeError("Gemini request failed")

    result = compare_question(
        "경비 처리에 필요한 증빙은 무엇인가요?",
        {},
        settings=settings(),
        gemini_project="demo-project",
        gemini_location="us-central1",
        gemini_model="gemini-2.5-flash",
        local_answer=lambda *args, **kwargs: answer(),
        gemini_answer=failed_gemini,
    )

    assert result["local"]["status"] == "ok"
    assert result["api"]["status"] == "error"
    assert "Gemini request failed" in result["api"]["error"]
