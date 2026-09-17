from pathlib import Path


def test_presentation_index_contains_split_chat_labels():
    html = Path("presentation/index.html").read_text(encoding="utf-8")

    assert "Local LLM 챗봇" in html
    assert "API 모델 챗봇" in html
    assert "Vertex Gemini" in html
    assert "localModelToggle" in html
    assert "localModelQwen" in html
    assert "localModelExaone" in html
    assert "qwen3:4b-instruct" in html
    assert "exaone3.5:7.8b" in html
    assert "chatForm" in html
    assert "chatInput" in html
    assert "sendButton" in html
    assert "clearChatButton" in html
    assert "localMessages" in html
    assert "apiMessages" in html
    assert "localModelName" in html
    assert "apiModelName" in html
    assert "localIntegrationStatus" in html
    assert "apiIntegrationStatus" in html
    assert "localStatus" not in html
    assert "apiStatus" not in html
    assert "채팅 전송" in html
    assert "대화 초기화" in html
    assert "저장된 결과 불러오기" not in html


def test_presentation_javascript_calls_cases_and_compare_endpoints():
    js = Path("presentation/static/presentation.js").read_text(encoding="utf-8")

    assert 'fetch("/api/status")' in js
    assert 'fetch("/api/cases")' in js
    assert 'fetch("/api/compare"' in js
    assert 'method: "POST"' in js
    assert "selectedLocalModel" in js
    assert "local_model" in js


def test_presentation_javascript_renders_chat_turns_from_user_input():
    js = Path("presentation/static/presentation.js").read_text(encoding="utf-8")

    assert "async function sendChatTurn" in js
    assert "function appendUserTurn" in js
    assert "function appendAssistantTurn" in js
    assert "function appendMessage" in js
    assert 'els.chatForm.addEventListener("submit"' in js
    assert "renderPreparedCase" not in js
    assert "runLiveButton" not in js
    assert "localStatus" not in js
    assert "apiStatus" not in js
    assert "setLoading" not in js


def test_presentation_javascript_has_loading_and_answer_source_chips():
    js = Path("presentation/static/presentation.js").read_text(encoding="utf-8")

    assert "function appendLoadingTurn" in js
    assert "function updateLoadingMessage" in js
    assert "function clearLoadingTurns" in js
    assert "loading-message" in js
    assert "RAG 검색 중" in js
    assert "Local LLM 생성 중" in js
    assert "Gemini 모델 상태 확인 중" in js
    assert "function renderMessageSources" in js
    assert "source-chip" in js
    assert "function formatSourceLabel" in js
    assert "재택근무 규정" in js
    assert "scoreLabel" in js


def test_presentation_javascript_uses_friendly_korean_status_text():
    js = Path("presentation/static/presentation.js").read_text(encoding="utf-8")

    assert "friendlyPanelText" in js
    assert "Local LLM 응답 실패" in js
    assert "Gemini project가 아직 설정되지 않았습니다." in js
    assert "Gemini 응답 실패" in js


def test_presentation_javascript_logs_api_http_status_signals():
    js = Path("presentation/static/presentation.js").read_text(encoding="utf-8")

    assert "function logApiSignal" in js
    assert "console.info" in js
    assert "console.error" in js
    assert "httpStatus=${response.status}" in js
    assert "ok=${response.ok}" in js
    assert "httpStatus: response.status" in js
    assert 'logApiSignal("/api/status", response)' in js
    assert 'logApiSignal("/api/cases", response)' in js
    assert 'logApiSignal("/api/compare", response)' in js


def test_presentation_javascript_keeps_runtime_status_for_prepared_cases():
    js = Path("presentation/static/presentation.js").read_text(encoding="utf-8")

    assert "runtimeStatus" in js
    assert "state.runtimeStatus = payload" in js
    assert "const runtimePayload = state.runtimeStatus[side] || {}" in js
    assert "const effectivePayload = { ...runtimePayload, ...payload }" in js


def test_presentation_css_keeps_composer_sticky_and_styles_source_chips():
    css = Path("presentation/static/presentation.css").read_text(encoding="utf-8")

    assert ".chat-composer" in css
    assert "position: sticky" in css
    assert "bottom: 16px" in css
    assert ".source-chip" in css
    assert ".message.loading" in css
    assert ".status.pending" in css
    assert ".model-toggle" in css
    assert ".model-option" in css
