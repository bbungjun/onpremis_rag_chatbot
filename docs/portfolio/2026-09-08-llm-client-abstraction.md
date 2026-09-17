# 생성 모델 호출을 LLMClient 경계로 통합

## 한 줄 결론

Qwen과 Vertex Gemini 생성 경로에 중복돼 있던 검색·문맥 조립 흐름을
`app.rag_pipeline.answer_question` 하나로 통합하고, 생성 모델 차이는 `LLMClient` 구현체로
격리했다. Docker 전체 테스트 311건 중 309건이 통과하고 2건이 환경 조건으로 스킵됐으며,
로컬 Qwen RAG 샘플 질의에서 검색부터 생성·출처 반환까지 확인했다. 답변 품질과 성능의
Before/After 변화는 측정하지 않았다.

2026-09-18에 사용하지 않는 AWS 생성 경로를 제거했다. 아래 테스트 개수와 실행 시간은
제거 이전 실행에서 관찰된 값이며, 현재 유지되는 구현과 설계 판단만 기술한다.

## Before / 문제

Qwen과 Gemini 파이프라인이 같은 검색 흐름을 각각 가지고 있었다. 질문 해석,
dense/sparse 표현 생성, Qdrant 검색, parent 조문 확장, 프롬프트 조립, 빈 결과 fallback이
모델별 모듈에 중복돼 있어 공통 동작을 수정할 때 여러 경로를 함께 변경해야 했다.

생성 모델별 차이는 최종 호출 방식과 설정뿐이지만, 그 차이가 검색 파이프라인 전체의
복제로 이어졌다. 이 구조에서는 한 경로에만 보안 지침, context 제한, 검색 옵션 또는
fallback 수정이 반영될 위험이 있었다.

현재 유지되는 생성 경로는 다음 두 개다.

```text
기본 온프레미스 경로  Ollama / Qwen
비교·평가 경로        Vertex Gemini
```

## Why / 분석

검색과 문맥 조립은 생성 공급자를 알 필요가 없다. 반대로 생성 구현체는 이미 조립된
system 지시와 user/context 데이터를 받아 공급자 API에 전달하는 책임만 가지면 된다.

검토한 경계는 다음과 같다.

```text
A. 기존 함수 분기 유지
   변경은 작지만 모델이 추가될 때 공통 파이프라인의 조건문과 중복이 늘어난다.

B. 문자열 하나를 받는 generate(prompt) 인터페이스
   단순하지만 system 지시와 untrusted user/context 데이터의 분리를 보장하지 못한다.

C. generate(system_prompt, user_prompt) 인터페이스 (채택)
   공급자별 구현을 격리하면서 system/user 분리 계약을 인터페이스에 남긴다.
```

C는 Qwen 요청의 system 지시와 사용자·검색 문맥을 분리해야 한다는 제품 규칙을 유지하고,
기본 Ollama 호출을 Docker 밖의 호스트 서비스로 보내는 현재 온프레미스 구조도 바꾸지 않는다.

## Solution / 구현

`app/llm.py`에는 `LLMClient` 추상 클래스와 현재 두 구현체가 남아 있다.

```text
LLMClient.generate(system_prompt, user_prompt)
├─ OllamaLLM  -> chat_qwen
└─ GeminiLLM  -> chat_gemini_vertex
```

`app.rag_pipeline.answer_question`은 선택적 `llm` 인자를 받고, 생략 시 기존과 같이
`Settings`에서 `OllamaLLM`을 만든다. 임베딩, sparse 표현, Qdrant 검색, parent 확장,
프롬프트 조립, fallback, source 반환은 하나의 공통 경로가 담당한다.

Gemini 파이프라인은 공급자 설정을 해당 `LLMClient`로 변환해 공통 파이프라인에
주입하는 얇은 어댑터가 됐다. 공급자 이름은 진행 메시지와 타이밍 라벨에 반영된다.

기존 think 모드도 `OllamaLLM.from_settings`에서 `llm_think`를 받아 `chat_qwen`까지 전달한다.
따라서 `qwen3:4b-instruct`의 현재 `LLM_THINK=off` 설정은 리팩터링 뒤에도 유지된다.

## Verification

실행일: 2026-09-08, Windows 호스트 + Docker Desktop, Qdrant 1.18.2, Ollama 0.32.5.

자동화 테스트:

```text
docker compose up -d
  -> qdrant, rag-api, streamlit 실행

docker compose run --rm rag-api pytest -v
  -> 311 collected, 309 passed, 2 skipped, 0 failed (7.69s)

git diff --check origin/main...HEAD
  -> clean

GitHub Actions / PR #10
  -> lint SUCCESS, test SUCCESS
```

스킵 2건:

```text
tests/test_agent_setup_contract.py::test_tracked_files_do_not_contain_real_public_endpoint
  Docker 이미지에 git CLI 또는 .git 접근이 없어 스킵

tests/test_exaone_live.py::test_local_exaone_answers_structural_annual_leave_case
  RUN_EXAONE_LIVE_TEST=1이 설정되지 않아 스킵
```

서비스 검증:

```text
curl http://localhost:6333
  -> qdrant 1.18.2 응답

docker compose run --rm rag-api python -m app.healthcheck
  -> LLM model: qwen3:4b-instruct
     LLM think mode: off
     Qdrant URL: http://qdrant:6333
```

실제 Qwen RAG 질의:

```text
docker compose run --rm rag-api python scripts/ask_rag.py \
  "연차 신청은 며칠 전까지 해야 하나요?" --timing

-> 검색, parent 확장, Qwen 생성, source 반환 성공
-> 답변: 최소 3영업일 전까지 신청
-> 답변 근거 표기: 제39조 ③항
-> 반환 source에 datasets/docs/regulations.md#jo-39 포함
-> Qwen generation: 4.390s
```

첫 실행은 호스트 Ollama가 꺼져 있어 임베딩 단계에서 connection refused로 실패했다.
`ollama list`로 서비스를 기동하고 `bge-m3:latest`, `qwen3:4b-instruct` 모델을 확인한 뒤
동일 명령을 재실행해 성공했다. 이는 코드 회귀가 아니라 런타임 선행 조건이었다.

## After / 확인된 결과

- 현재 두 생성 경로가 동일한 검색·문맥 조립·fallback 구현을 사용한다.
- `LLMClient` 주입 시 기본 Qwen 호출을 건너뛰는 계약이 테스트로 확인됐다.
- 각 구현체가 system prompt와 user prompt를 분리된 인자로 기존 공급자 클라이언트에
  전달하는 것이 테스트로 확인됐다.
- Ollama think 설정 전달과 공급자별 진행·타이밍 라벨이 테스트로 확인됐다.
- 로컬 Qwen 기본 경로는 실제 규정 질문에 답하고 근거 source를 반환했다.

이 작업은 리팩터링이다. 같은 데이터셋의 답변 품질, 검색 지표, 지연 또는 자원 사용량을
변경 전후로 통제 측정하지 않았으므로 사용자 가치나 성능 개선을 주장하지 않는다.

## Evidence and Limitations

```text
PR              #10 refactor: isolate generation behind an LLMClient boundary
구현 커밋        9c4accb7de34d894ff58c1344f37c4018cf86c7d
검증 기준 main  ba26d7d1d0496934951e79996ecf20e1509f0ecf
테스트           309 passed, 2 skipped
Qdrant           1.18.2
Ollama           0.32.5
생성 모델        qwen3:4b-instruct
임베딩 모델      bge-m3:latest
```

남은 한계:

1. Gemini는 단위·통합 테스트의 주입 함수로 검증했으며 실제 클라우드 API 호출은
   자격 증명과 비용이 필요한 관계로 실행하지 않았다.
2. EXAONE 실제 생성 경로는 환경 플래그가 없어 스킵됐다.
3. 리팩터링 전후 답변 동등성, 품질, 지연, GPU/메모리 사용량은 측정하지 않았다.
4. 기존 prompt injection 평가를 이 브랜치에서 다시 실행하지 않았다. system/user 분리 계약은
   유지되지만, 알려진 canary 유출 문제가 개선됐다는 뜻은 아니다.
5. 컨테이너에는 `ruff` 실행 파일이 없어 로컬 lint를 재실행하지 못했다. PR의 GitHub Actions
   `lint`와 `test` 체크는 모두 성공했다.
