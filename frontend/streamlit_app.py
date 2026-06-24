from __future__ import annotations

import logging
import os
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

import httpx
import streamlit as st

API_BASE = os.getenv("RAG_API_URL", "http://localhost:8000")
OLLAMA_ENDPOINT = f"{API_BASE}/api/ask/qwen"
QWEN_ENDPOINT = OLLAMA_ENDPOINT
GEMINI_ENDPOINT = f"{API_BASE}/api/ask/gemini"
BEDROCK_ENDPOINT = f"{API_BASE}/api/ask/bedrock"
HEALTH_ENDPOINT = f"{API_BASE}/health/services"
ASK_TIMEOUT_SECONDS = 180.0
HEALTH_TIMEOUT_SECONDS = 6.0
OLLAMA_MODEL_OPTIONS = {
    "Qwen": "qwen3:4b-instruct",
    "EXAONE": "exaone3.5:7.8b",
}
OLLAMA_MESSAGE_KEYS = {
    "qwen3:4b-instruct": "ollama_qwen_messages",
    "exaone3.5:7.8b": "ollama_exaone_messages",
}
GEMINI_MODEL_OPTIONS = {
    "Gemini 2.5 Flash": "gemini-2.5-flash",
    "Gemini 2.5 Pro": "gemini-2.5-pro",
}
BEDROCK_MODEL_OPTIONS = {
    "Claude Sonnet 4.6": "jp.anthropic.claude-sonnet-4-6",
    "Claude Opus 4.6": "global.anthropic.claude-opus-4-6-v1",
    "Claude Sonnet 4.5": "global.anthropic.claude-sonnet-4-5-20250929-v1:0",
}
DEFAULT_GEMINI_LOCATION = os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1")
DEFAULT_GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
DEFAULT_GEMINI_PROJECT = os.getenv("GOOGLE_CLOUD_PROJECT") or os.getenv("GCP_PROJECT_ID", "")
DEFAULT_BEDROCK_REGION = os.getenv("BEDROCK_REGION", "ap-northeast-3")
DEFAULT_BEDROCK_MODEL = os.getenv("BEDROCK_MODEL_ID", "jp.anthropic.claude-sonnet-4-6")
LOGGER = logging.getLogger("llmenhance.liveqa")
LOGGER.setLevel(getattr(logging, os.getenv("LIVEQA_LOG_LEVEL", "INFO").upper(), logging.INFO))
if not LOGGER.handlers:
    _liveqa_handler = logging.StreamHandler()
    _liveqa_handler.setFormatter(logging.Formatter("%(levelname)s:%(name)s:%(message)s"))
    LOGGER.addHandler(_liveqa_handler)

STATUS_LABELS = {
    "ok": "정상",
    "warning": "확인 필요",
    "error": "오류",
    "unknown": "미확인",
}


def main() -> None:
    st.set_page_config(
        page_title="사내 규정 챗봇 비교",
        layout="wide",
    )
    _init_state()
    _render_sidebar()
    _render_main()


def _init_state() -> None:
    existing_ollama_messages = st.session_state.get(
        "ollama_messages", st.session_state.get("qwen_messages", [])
    )
    defaults: dict[str, Any] = {
        "ollama_qwen_messages": existing_ollama_messages,
        "ollama_exaone_messages": [],
        "gemini_messages": [],
        "bedrock_messages": [],
        "service_status": None,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value
    st.session_state["ollama_messages"] = st.session_state["ollama_qwen_messages"]
    st.session_state["qwen_messages"] = st.session_state["ollama_qwen_messages"]


def _render_sidebar() -> None:
    with st.sidebar:
        st.header("서비스 상태")
        col_refresh, col_auto = st.columns([2, 1])
        with col_refresh:
            refresh = st.button("새로고침", use_container_width=True)
        with col_auto:
            auto_check = st.checkbox("자동", value=True, help="페이지 로드 시 상태를 확인합니다.")

        if refresh or (auto_check and st.session_state.service_status is None):
            with st.spinner("상태 확인 중..."):
                st.session_state.service_status = _fetch_service_status()

        status = st.session_state.service_status
        if status is None:
            st.caption("새로고침을 눌러 서비스 상태를 확인하세요.")
            return

        st.divider()
        _render_status_line("API 서버", status.get("api", {}))
        _render_status_line("Ollama", status.get("ollama", {}))
        _render_status_line("Qdrant", status.get("qdrant", {}))
        _render_status_line("Vertex Gemini", status.get("gemini", {}))
        _render_status_line("AWS Bedrock", status.get("bedrock", {}))

        st.divider()
        overall = _overall_status(status)
        if overall == "ok":
            st.success("모든 서비스 정상")
        elif overall == "warning":
            st.warning("일부 서비스 확인 필요")
        else:
            st.error("연결 오류 발생")

        st.divider()
        _render_cloud_session_controls()


def _render_main() -> None:
    st.title("사내 규정 챗봇 모델 비교")

    status = st.session_state.service_status
    cloud_configs = _cloud_session_configs()
    col_ollama, col_gemini, col_bedrock = st.columns(3)

    with col_ollama:
        _render_panel_header("EC2 Ollama", status, "ollama")
        selected_ollama_model = _render_ollama_model_selector()
        ollama_messages_key = _ollama_messages_key(selected_ollama_model)
        _ensure_message_state(ollama_messages_key)
        st.caption("온프레미스 RAG 답변 생성")
        st.divider()
        _render_chat_history(st.session_state[ollama_messages_key])

    with col_gemini:
        _render_panel_header("Vertex Gemini", status, "gemini")
        st.caption("클라우드 API RAG 답변 생성")
        st.divider()
        _render_chat_history(st.session_state.gemini_messages)

    with col_bedrock:
        _render_panel_header("AWS Bedrock", status, "bedrock")
        st.caption("AWS Bedrock RAG")
        st.divider()
        _render_chat_history(st.session_state.bedrock_messages)

    question = st.chat_input("사내 규정에 대해 질문하세요.")
    if not question:
        return

    active_model_keys = _active_model_keys(cloud_configs)
    active_message_keys = _active_message_keys(
        cloud_configs, selected_ollama_model=selected_ollama_model
    )
    _append_user_message(question, active_message_keys.values())
    payload = {"question": question}
    live_containers = {
        "ollama": _render_live_user_message(col_ollama, question),
    }
    if cloud_configs["gemini"]["enabled"]:
        live_containers["gemini"] = _render_live_user_message(col_gemini, question)
    if cloud_configs["bedrock"]["enabled"]:
        live_containers["bedrock"] = _render_live_user_message(col_bedrock, question)

    with st.spinner(_liveqa_spinner_text(active_model_keys)):
        for model_key, result in _iter_model_results(
            payload,
            selected_ollama_model=selected_ollama_model,
            gemini_config=cloud_configs["gemini"],
            bedrock_config=cloud_configs["bedrock"],
        ):
            messages_key = active_message_keys[model_key]
            _append_assistant_message(messages_key, result)
            with live_containers[model_key]:
                _render_message(st.session_state[messages_key][-1])


def _render_live_user_message(column: Any, question: str) -> Any:
    with column:
        container = st.container()
        with container:
            _render_message({"role": "user", "content": question})
        return container


def _fetch_service_status() -> dict[str, Any]:
    try:
        response = httpx.get(HEALTH_ENDPOINT, timeout=HEALTH_TIMEOUT_SECONDS)
        response.raise_for_status()
        status = response.json()
        _log_liveqa_service_status(status)
        return status
    except Exception as exc:
        status = {
            "api": {"status": "error", "detail": f"API 서버 연결 실패: {exc}"},
            "ollama": {"status": "unknown", "detail": ""},
            "qdrant": {"status": "unknown", "detail": ""},
            "gemini": {"status": "unknown", "detail": ""},
            "bedrock": {"status": "unknown", "detail": ""},
        }
        _log_liveqa_service_status(status)
        return status


def _render_ollama_model_selector() -> str:
    label = st.radio(
        "Ollama 모델",
        options=list(OLLAMA_MODEL_OPTIONS.keys()),
        horizontal=True,
        key="selected_ollama_model_label",
    )
    model = OLLAMA_MODEL_OPTIONS[str(label)]
    st.caption(f"선택 모델: `{model}`")
    return model


def _render_cloud_session_controls() -> None:
    st.subheader("Cloud sessions")

    gemini_enabled = st.toggle(
        "Gemini",
        value=_env_bool("ENABLE_GEMINI_PANEL", True),
        key="gemini_enabled",
    )
    if gemini_enabled:
        st.text_input("Gemini project", value=DEFAULT_GEMINI_PROJECT, key="gemini_project")
        st.text_input("Gemini location", value=DEFAULT_GEMINI_LOCATION, key="gemini_location")
        _render_model_text_input(
            "Gemini model",
            GEMINI_MODEL_OPTIONS,
            DEFAULT_GEMINI_MODEL,
            "gemini_model",
        )
        st.number_input(
            "Gemini thinking budget",
            value=int(os.getenv("GEMINI_THINKING_BUDGET", "0")),
            step=1,
            key="gemini_thinking_budget",
        )

    bedrock_enabled = st.toggle(
        "Bedrock",
        value=_env_bool("ENABLE_BEDROCK_PANEL", bool(DEFAULT_BEDROCK_MODEL)),
        key="bedrock_enabled",
    )
    if bedrock_enabled:
        st.text_input("Bedrock region", value=DEFAULT_BEDROCK_REGION, key="bedrock_region")
        _render_model_text_input(
            "Bedrock model/profile",
            BEDROCK_MODEL_OPTIONS,
            DEFAULT_BEDROCK_MODEL,
            "bedrock_model_id",
        )


def _render_model_text_input(
    label: str,
    options: dict[str, str],
    default_value: str,
    key: str,
) -> str:
    labels = list(options)
    default_label = next(
        (item for item in labels if options[item] == default_value),
        labels[0],
    )
    selected_label = st.selectbox(
        f"{label} preset",
        options=labels,
        index=labels.index(default_label),
        key=f"{key}_preset",
    )
    return st.text_input(label, value=options[str(selected_label)], key=key)


def _cloud_session_configs() -> dict[str, dict[str, Any]]:
    return {
        "gemini": {
            "enabled": bool(
                st.session_state.get("gemini_enabled", _env_bool("ENABLE_GEMINI_PANEL", True))
            ),
            "project": st.session_state.get("gemini_project", DEFAULT_GEMINI_PROJECT),
            "location": st.session_state.get("gemini_location", DEFAULT_GEMINI_LOCATION),
            "model": st.session_state.get("gemini_model", DEFAULT_GEMINI_MODEL),
            "thinking_budget": st.session_state.get(
                "gemini_thinking_budget", int(os.getenv("GEMINI_THINKING_BUDGET", "0"))
            ),
        },
        "bedrock": {
            "enabled": bool(
                st.session_state.get(
                    "bedrock_enabled",
                    _env_bool("ENABLE_BEDROCK_PANEL", bool(DEFAULT_BEDROCK_MODEL)),
                )
            ),
            "region": st.session_state.get("bedrock_region", DEFAULT_BEDROCK_REGION),
            "model_id": st.session_state.get("bedrock_model_id", DEFAULT_BEDROCK_MODEL),
        },
    }


def _active_model_keys(cloud_configs: dict[str, dict[str, Any]]) -> list[str]:
    keys = ["ollama"]
    if cloud_configs["gemini"]["enabled"]:
        keys.append("gemini")
    if cloud_configs["bedrock"]["enabled"]:
        keys.append("bedrock")
    return keys


def _active_message_keys(
    cloud_configs: dict[str, dict[str, Any]], *, selected_ollama_model: str
) -> dict[str, str]:
    keys = {"ollama": _ollama_messages_key(selected_ollama_model)}
    if cloud_configs["gemini"]["enabled"]:
        keys["gemini"] = "gemini_messages"
    if cloud_configs["bedrock"]["enabled"]:
        keys["bedrock"] = "bedrock_messages"
    return keys


def _ollama_messages_key(selected_ollama_model: str) -> str:
    return OLLAMA_MESSAGE_KEYS.get(selected_ollama_model, "ollama_messages")


def _ask_both_models(
    payload: dict[str, Any],
    *,
    selected_ollama_model: str,
    gemini_config: dict[str, Any] | None = None,
    bedrock_config: dict[str, Any] | None = None,
) -> dict[str, dict[str, Any]]:
    return {
        model_key: result
        for model_key, result in _iter_model_results(
            payload,
            selected_ollama_model=selected_ollama_model,
            gemini_config=gemini_config,
            bedrock_config=bedrock_config,
        )
    }


def _iter_model_results(
    payload: dict[str, Any],
    *,
    selected_ollama_model: str,
    gemini_config: dict[str, Any] | None = None,
    bedrock_config: dict[str, Any] | None = None,
) -> Any:
    requests = _model_requests(
        payload,
        selected_ollama_model=selected_ollama_model,
        gemini_config=gemini_config,
        bedrock_config=bedrock_config,
    )
    _log_liveqa_api_links(requests)
    with ThreadPoolExecutor(max_workers=len(requests)) as executor:
        futures = {
            executor.submit(_call_rag, endpoint, request_payload): (
                model_key,
                endpoint,
                request_payload,
            )
            for model_key, endpoint, request_payload in requests
        }
        for future in as_completed(futures):
            model_key, _endpoint, _request_payload = futures[future]
            result = future.result()
            _log_liveqa_api_result(model_key, result)
            yield model_key, result


def _model_requests(
    payload: dict[str, Any],
    *,
    selected_ollama_model: str,
    gemini_config: dict[str, Any] | None,
    bedrock_config: dict[str, Any] | None,
) -> list[tuple[str, str, dict[str, Any]]]:
    requests = [
        ("ollama", OLLAMA_ENDPOINT, {**payload, "llm_model": selected_ollama_model}),
    ]

    if _provider_enabled(gemini_config, default=True):
        requests.append(("gemini", GEMINI_ENDPOINT, _gemini_payload(payload, gemini_config or {})))

    if _provider_enabled(bedrock_config, default=False):
        requests.append(
            ("bedrock", BEDROCK_ENDPOINT, _bedrock_payload(payload, bedrock_config or {}))
        )

    return requests


def _provider_enabled(config: dict[str, Any] | None, *, default: bool) -> bool:
    if config is None:
        return default
    return bool(config.get("enabled", default))


def _gemini_payload(payload: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    return _payload_with_optional_values(
        payload,
        {
            "gemini_project": config.get("project"),
            "gemini_location": config.get("location"),
            "gemini_model": config.get("model"),
            "gemini_thinking_budget": config.get("thinking_budget"),
        },
    )


def _bedrock_payload(payload: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    return _payload_with_optional_values(
        payload,
        {
            "bedrock_region": config.get("region"),
            "bedrock_model_id": config.get("model_id"),
        },
    )


def _payload_with_optional_values(
    payload: dict[str, Any], optional_values: dict[str, Any]
) -> dict[str, Any]:
    merged = dict(payload)
    for key, value in optional_values.items():
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        merged[key] = value
    return merged


def _call_rag(url: str, payload: dict[str, Any]) -> dict[str, Any]:
    try:
        response = httpx.post(url, json=payload, timeout=ASK_TIMEOUT_SECONDS)
        response.raise_for_status()
        return response.json()
    except httpx.HTTPStatusError as exc:
        detail = _error_detail(exc.response)
        return {
            "answer": f"서버 오류 ({exc.response.status_code}){': ' + detail if detail else ''}",
            "sources": [],
            "elapsed_ms": 0,
        }
    except httpx.ConnectError:
        return {"answer": "API 서버에 연결할 수 없습니다.", "sources": [], "elapsed_ms": 0}
    except httpx.TimeoutException:
        return {"answer": "응답 시간이 초과되었습니다.", "sources": [], "elapsed_ms": 0}
    except Exception as exc:
        return {"answer": f"오류: {exc}", "sources": [], "elapsed_ms": 0}


def _error_detail(response: httpx.Response) -> str:
    try:
        detail = response.json().get("detail", "")
    except Exception:
        return ""
    return str(detail)


def _append_user_message(question: str, message_keys: Iterable[str] | None = None) -> None:
    user_message = {"role": "user", "content": question}
    for messages_key in message_keys or ["ollama_qwen_messages", "gemini_messages"]:
        _ensure_message_state(messages_key)
        st.session_state[messages_key].append(user_message)


def _append_assistant_message(messages_key: str, result: dict[str, Any]) -> None:
    _ensure_message_state(messages_key)
    st.session_state[messages_key].append(
        {
            "role": "assistant",
            "content": result.get("answer", ""),
            "sources": result.get("sources", []),
            "elapsed_ms": result.get("elapsed_ms"),
        }
    )


def _render_panel_header(title: str, status: dict[str, Any] | None, service_key: str) -> None:
    if status is None:
        st.subheader(title)
        return

    service = status.get(service_key, {})
    label = STATUS_LABELS.get(service.get("status", "unknown"), "미확인")
    st.subheader(f"{title} · {label}")


def _render_chat_history(messages: list[dict[str, Any]]) -> None:
    for message in messages:
        _render_message(message)


def _render_message(message: dict[str, Any]) -> None:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])
        if message["role"] == "assistant":
            _render_sources(message.get("sources") or [])
            elapsed = message.get("elapsed_ms")
            if elapsed:
                st.caption(f"{elapsed:,}ms")


def _render_sources(sources: list[dict[str, Any]]) -> None:
    if not sources:
        return
    with st.expander(f"참고 문서 {len(sources)}건"):
        for index, source in enumerate(sources, start=1):
            source_path = str(source.get("source_path", ""))
            source_name = source_path.rsplit("/", maxsplit=1)[-1] or source_path
            chunk_id = source.get("chunk_id", "")
            score = source.get("score")
            score_text = f" · score {float(score):.3f}" if isinstance(score, (int, float)) else ""
            st.markdown(f"**{index}.** `{source_name}` · `{chunk_id}`{score_text}")
            if source_path:
                st.caption(source_path)


def _render_status_line(label: str, service: dict[str, Any]) -> None:
    status = service.get("status", "unknown")
    status_label = STATUS_LABELS.get(status, status)
    detail = service.get("detail", "")
    st.markdown(f"**{label}** · {status_label}")
    if detail:
        st.caption(str(detail))


def _env_bool(name: str, default: bool) -> bool:
    raw_value = os.getenv(name)
    if raw_value is None or raw_value.strip() == "":
        return default
    return raw_value.strip().lower() in {"1", "true", "yes", "on"}


def _overall_status(status: dict[str, Any]) -> str:
    service_statuses = [
        service.get("status", "unknown") for service in status.values() if isinstance(service, dict)
    ]
    if any(item == "error" for item in service_statuses):
        return "error"
    if any(item in {"warning", "unknown"} for item in service_statuses):
        return "warning"
    return "ok"


def _ensure_message_state(messages_key: str) -> None:
    if messages_key not in st.session_state:
        st.session_state[messages_key] = []


def _liveqa_spinner_text(active_model_keys: list[str]) -> str:
    if active_model_keys == ["ollama"]:
        return "선택한 Ollama 모델에서 답변을 생성하는 중..."
    return "선택한 Ollama 모델과 활성 Cloud 세션에서 답변을 생성하는 중..."


def _log_liveqa_service_status(status: dict[str, Any]) -> None:
    for provider, service in status.items():
        if not isinstance(service, dict):
            continue
        LOGGER.info(
            "LIVEQA_SERVICE_STATUS provider=%s status=%s detail=%s",
            provider,
            service.get("status", "unknown"),
            str(service.get("detail", "")),
        )


def _log_liveqa_api_links(requests: list[tuple[str, str, dict[str, Any]]]) -> None:
    for provider, endpoint, payload in requests:
        LOGGER.info(
            "LIVEQA_API_LINKED provider=%s endpoint=%s model=%s enabled=true",
            provider,
            endpoint,
            _request_model_name(provider, payload),
        )


def _log_liveqa_api_result(provider: str, result: dict[str, Any]) -> None:
    LOGGER.info(
        "LIVEQA_API_RESULT provider=%s status=ok sources=%s elapsed_ms=%s",
        provider,
        len(result.get("sources") or []),
        result.get("elapsed_ms", 0),
    )


def _request_model_name(provider: str, payload: dict[str, Any]) -> str:
    if provider == "ollama":
        return str(payload.get("llm_model", ""))
    if provider == "gemini":
        return str(payload.get("gemini_model", DEFAULT_GEMINI_MODEL))
    if provider == "bedrock":
        return str(payload.get("bedrock_model_id", DEFAULT_BEDROCK_MODEL))
    return ""


if __name__ == "__main__":
    main()
