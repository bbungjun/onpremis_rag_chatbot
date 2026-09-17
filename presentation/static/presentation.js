const state = {
  cases: [],
  runtimeStatus: {},
  isSending: false,
  loadingTimers: [],
};

const els = {
  chatForm: document.querySelector("#chatForm"),
  chatInput: document.querySelector("#chatInput"),
  sendButton: document.querySelector("#sendButton"),
  clearChatButton: document.querySelector("#clearChatButton"),
  sampleQuestions: document.querySelector("#sampleQuestions"),
  localModelToggle: document.querySelector("#localModelToggle"),
  localModelInputs: document.querySelectorAll('input[name="localModel"]'),
  localIntegrationStatus: document.querySelector("#localIntegrationStatus"),
  localModelName: document.querySelector("#localModelName"),
  localMessages: document.querySelector("#localMessages"),
  localLatency: document.querySelector("#localLatency"),
  localSourceCount: document.querySelector("#localSourceCount"),
  apiIntegrationStatus: document.querySelector("#apiIntegrationStatus"),
  apiModelName: document.querySelector("#apiModelName"),
  apiMessages: document.querySelector("#apiMessages"),
  apiLatency: document.querySelector("#apiLatency"),
  apiSourceCount: document.querySelector("#apiSourceCount"),
  sourceList: document.querySelector("#sourceList"),
  takeaway: document.querySelector("#takeaway"),
};

const SOURCE_TITLES = {
  "leave-policy.md": "연차 및 휴가 규정",
  "remote-work-policy.md": "재택근무 규정",
  "travel-policy.md": "출장비 규정",
  "expense-policy.md": "경비 처리 규정",
  "vendor-payment-policy.md": "협력사 지급 규정",
  "onboarding-guide.md": "온보딩 가이드",
};

async function loadRuntimeStatus() {
  try {
    const response = await fetch("/api/status");
    logApiSignal("/api/status", response);
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.error || "runtime status request failed");
    }
    renderRuntimeStatus(payload);
  } catch (error) {
    logApiError("/api/status", error);
    throw error;
  }
}

function renderRuntimeStatus(payload) {
  state.runtimeStatus = payload;
  renderIntegrationStatus("local", payload.local);
  renderIntegrationStatus("api", payload.api);
}

async function loadCases() {
  let payload;
  try {
    const response = await fetch("/api/cases");
    logApiSignal("/api/cases", response);
    payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.error || "case list request failed");
    }
  } catch (error) {
    logApiError("/api/cases", error);
    throw error;
  }
  state.cases = payload.cases || [];
  renderSampleQuestions();
}

function renderSampleQuestions() {
  els.sampleQuestions.innerHTML = "";
  state.cases.forEach((item) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "sample-chip";
    button.textContent = item.question;
    button.addEventListener("click", () => {
      els.chatInput.value = item.question;
      els.chatInput.focus();
    });
    els.sampleQuestions.append(button);
  });
}

async function sendChatTurn(event) {
  event.preventDefault();
  if (state.isSending) return;
  const question = els.chatInput.value.trim();
  if (!question) return;

  appendUserTurn(question);
  appendLoadingTurn();
  setSending(true);
  els.chatInput.value = "";

  let response;
  let payload;
  try {
    response = await fetch("/api/compare", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question, local_model: selectedLocalModel() }),
    });
    logApiSignal("/api/compare", response);
    payload = await response.json();
  } catch (error) {
    logApiError("/api/compare", error);
    clearLoadingTurns();
    appendErrorTurn(error.message);
    setSending(false);
    return;
  }

  if (!response.ok) {
    const message = payload.error || "compare request failed";
    logApiError("/api/compare", new Error(message));
    clearLoadingTurns();
    appendErrorTurn(message);
    setSending(false);
    return;
  }

  clearLoadingTurns();
  appendAssistantTurn(payload);
  setSending(false);
}

function appendUserTurn(question) {
  appendMessage("local", "user", question);
  appendMessage("api", "user", question);
}

function appendAssistantTurn(result) {
  renderPanel("local", result.local);
  renderPanel("api", result.api);
  renderSources(result.shared_sources || []);
  els.takeaway.textContent =
    result.takeaway ||
    "사용자 질문마다 같은 검색 근거를 조회하고, 두 모델 답변과 출처를 나란히 비교합니다.";
}

function appendErrorTurn(message) {
  const panel = {
    status: "error",
    answer: "",
    sources: [],
    error: message,
    generation_seconds: 0,
  };
  renderPanel("local", panel);
  renderPanel("api", panel);
}

function renderPanel(side, panel) {
  const prefix = side === "local" ? "local" : "api";
  const text = friendlyPanelText(side, panel);
  renderIntegrationStatus(side, panel);
  appendMessage(side, panelRole(panel.status), text, panel);
  els[`${prefix}Latency`].textContent =
    panel.status === "pending"
      ? "생성 시간 -"
      : `생성 시간 ${Number(panel.generation_seconds || 0).toFixed(1)}초`;
  els[`${prefix}SourceCount`].textContent = `출처 ${(panel.sources || []).length}개`;
}

function appendMessage(side, role, text, panel = {}) {
  const stream = side === "local" ? els.localMessages : els.apiMessages;
  stream.querySelector(".empty-state")?.remove();

  const message = document.createElement("article");
  message.className = `message ${role}`;
  if (role === "loading") {
    message.classList.add("loading-message");
  }

  const label = document.createElement("div");
  label.className = "message-label";
  label.textContent = messageLabel(side, role);

  const body = document.createElement("div");
  body.className = "message-body";
  body.textContent = text || "표시할 답변이 없습니다.";

  message.append(label, body);

  if (role !== "user" && role !== "loading" && role !== "notice") {
    const meta = document.createElement("div");
    meta.className = "message-meta";
    meta.textContent = `생성 시간 ${Number(panel.generation_seconds || 0).toFixed(
      1
    )}초 · 출처 ${(panel.sources || []).length}개`;
    message.append(meta);
    renderMessageSources(message, panel.sources || []);
  }

  stream.append(message);
  stream.scrollTop = stream.scrollHeight;
}

function appendLoadingTurn() {
  appendMessage("local", "loading", "RAG 검색 중 · Local LLM 생성 준비 중");
  appendMessage("api", "loading", "Gemini 모델 상태 확인 중");
  state.loadingTimers.push(
    window.setTimeout(() => {
      updateLoadingMessage("local", "검색 근거 구성 완료 · Local LLM 생성 중");
      updateLoadingMessage("api", "Gemini 모델 상태 확인 중");
    }, 900),
    window.setTimeout(() => {
      updateLoadingMessage("local", "Local LLM 생성 중 · 응답이 길어지고 있습니다");
    }, 3200)
  );
}

function updateLoadingMessage(side, text) {
  const stream = side === "local" ? els.localMessages : els.apiMessages;
  const loadingBody = stream.querySelector(".loading-message .message-body");
  if (loadingBody) {
    loadingBody.textContent = text;
  }
}

function clearLoadingTurns() {
  state.loadingTimers.forEach((timer) => window.clearTimeout(timer));
  state.loadingTimers = [];
  document.querySelectorAll(".loading-message").forEach((element) => element.remove());
}

function messageLabel(side, role) {
  if (role === "user") return "사용자";
  if (role === "error") return "오류";
  if (role === "notice") return "안내";
  if (role === "loading") return "진행 중";
  return side === "local" ? "Local LLM" : "API 모델";
}

function panelRole(status) {
  if (status === "error") return "error";
  if (status === "pending") return "notice";
  return "assistant";
}

function friendlyPanelText(side, panel) {
  if (panel.status === "pending") {
    return panel.answer || "Gemini project가 아직 설정되지 않았습니다.";
  }
  if (panel.status !== "error") {
    return panel.answer;
  }

  const error = panel.error || "";
  if (side === "local") {
    return "Local LLM 응답 실패. 자세한 원인은 서버 로그를 확인하세요.";
  }
  return "Gemini 응답 실패. 자세한 원인은 서버 로그를 확인하세요.";
}

function logApiSignal(endpoint, response) {
  console.info(
    `[presentation-api] ${endpoint} httpStatus=${response.status} ok=${response.ok} statusText=${response.statusText}`,
    {
      endpoint,
      httpStatus: response.status,
      ok: response.ok,
      statusText: response.statusText,
    }
  );
}

function logApiError(endpoint, error) {
  console.error(`[presentation-api] ${endpoint} failed message=${error.message}`, {
    endpoint,
    message: error.message,
  });
}

function setSending(isSending) {
  state.isSending = isSending;
  els.sendButton.disabled = isSending;
  els.clearChatButton.disabled = isSending;
  els.chatInput.disabled = isSending;
  els.localModelInputs.forEach((input) => {
    input.disabled = isSending;
  });
  els.sendButton.textContent = isSending ? "응답 대기 중" : "채팅 전송";
}

function clearChat() {
  clearLoadingTurns();
  resetStream("local");
  resetStream("api");
  els.localLatency.textContent = "생성 시간 -";
  els.localSourceCount.textContent = "출처 0개";
  els.apiLatency.textContent = "생성 시간 -";
  els.apiSourceCount.textContent = "출처 0개";
  renderSources([]);
  els.takeaway.textContent =
    "질문을 보내면 같은 RAG 근거를 기준으로 Local LLM과 API 모델 답변을 나란히 비교합니다.";
  els.chatInput.focus();
}

function resetStream(side) {
  const stream = side === "local" ? els.localMessages : els.apiMessages;
  const label = side === "local" ? "Local LLM" : "API 모델";
  stream.innerHTML = "";
  const empty = document.createElement("div");
  empty.className = "empty-state";
  empty.textContent = `질문을 입력하면 ${label} 답변이 이곳에 쌓입니다.`;
  stream.append(empty);
}

function renderIntegrationStatus(side, payload = {}) {
  const prefix = side === "local" ? "local" : "api";
  const runtimePayload = state.runtimeStatus[side] || {};
  const effectivePayload = { ...runtimePayload, ...payload };
  if (effectivePayload.model) {
    els[`${prefix}ModelName`].textContent = `model: ${effectivePayload.model}`;
  }
  const status = effectivePayload.integration_status || "";
  const message = effectivePayload.integration_message || "연동 상태 확인 전";
  setStatus(els[`${prefix}IntegrationStatus`], message, status);
}

function selectedLocalModel() {
  return (
    document.querySelector('input[name="localModel"]:checked')?.value ||
    "qwen3:4b-instruct"
  );
}

function renderSelectedLocalModel() {
  els.localModelName.textContent = `model: ${selectedLocalModel()}`;
}

function setStatus(element, text, statusClass = "") {
  element.textContent = text;
  element.classList.remove("ok", "error", "pending");
  if (statusClass) {
    element.classList.add(statusClass);
  }
}

function renderSources(sources) {
  els.sourceList.innerHTML = "";
  if (sources.length === 0) {
    const item = document.createElement("li");
    item.textContent = "표시할 출처가 없습니다.";
    els.sourceList.append(item);
    return;
  }
  sources.forEach((source) => {
    const item = document.createElement("li");
    item.textContent = formatSourceLabel(source);
    els.sourceList.append(item);
  });
}

function renderMessageSources(message, sources = []) {
  if (sources.length === 0) return;

  const sourceList = document.createElement("div");
  sourceList.className = "message-sources";
  sources.forEach((source) => {
    const chip = document.createElement("span");
    chip.className = "source-chip";
    chip.textContent = formatSourceLabel(source);
    sourceList.append(chip);
  });
  message.append(sourceList);
}

function formatSourceLabel(source) {
  const sourcePath = source.source_path || "";
  const fileName = sourcePath.split("/").pop() || sourcePath;
  const title = SOURCE_TITLES[fileName] || fileName.replace(/\.md$/, "");
  const department = sourcePath.includes("/hr/") ? "HR" : sourcePath.includes("/finance/") ? "Finance" : "문서";
  const score = Number(source.score);
  const scoreLabel = Number.isFinite(score) ? `score ${score.toFixed(2)}` : "score -";
  return `${title} · ${department} · ${scoreLabel}`;
}

els.chatForm.addEventListener("submit", sendChatTurn);
els.clearChatButton.addEventListener("click", clearChat);
els.localModelInputs.forEach((input) => {
  input.addEventListener("change", renderSelectedLocalModel);
});

clearChat();
Promise.all([loadRuntimeStatus(), loadCases()]).catch((error) => {
  els.takeaway.textContent = `발표 화면 초기화 중 문제가 발생했습니다: ${error.message}`;
});
