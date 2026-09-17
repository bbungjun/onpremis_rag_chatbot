# 사용하지 않는 AWS 생성 경로 제거 (2026-09-18)

## Before / 문제

사용 계획이 없는 AWS 관리형 생성 경로가 32개 추적 파일의 440줄에 남아 있었다. 서버에는 별도 답변 route와 상태 항목, Streamlit에는 세 번째 패널과 모델 설정, 발표용 비교 화면에는 공급자 연결과 저장된 예시 답변이 있었다. 전용 AWS SDK 의존성과 호스트 `.aws` 마운트도 이 경로 때문에 필요했다. 로컬 Python 기준선은 `310 passed, 1 skipped`였지만, 사용하지 않는 경로의 테스트와 설정도 유지해야 했다.

## Why / 분석

현재 제품의 기본 답변은 로컬 Ollama/Qwen이고, Gemini는 별도 비교 경로다. 사용하지 않는 AWS 생성 경로는 운영자가 모델 ID와 자격 증명을 관리해야 하는 부담을 만들면서 MVP의 검색·답변 품질에는 기여하지 않는다. 발표 화면의 두 번째 패널은 이미 존재하는 Gemini RAG 경로에 연결할 수 있었다. 이전 공급자의 저장 답변을 다른 모델 결과로 재표기하면 평가 증거가 왜곡되므로 샘플에서는 질문과 필터만 남겼다.

## Solution / 구현

- 전용 SDK 클라이언트, RAG wrapper, `LLMClient` 구현체, 서버 endpoint/요청 필드/health 항목, Streamlit 패널·설정을 제거했다.
- 전용 AWS SDK 의존성, `.aws` 컨테이너 마운트, 환경 변수 예시를 제거했다.
- 발표용 비교 API와 상태를 Vertex Gemini 경로에 연결했다. 샘플 데이터에는 질문과 필터만 남겼다.
- 아키텍처 SVG, README, 로컬 설치 안내와 설계·포트폴리오 문서를 현재 경로에 맞췄다. 과거 공급자 전용 구현 계획은 Git 이력에 남기고 작업 트리에서는 제거했다.

## Verification / 검증

| 항목 | 결과 |
| --- | --- |
| 실패 재현 | 변경 전 서버 답변 route 3개와 health의 추가 공급자 필드가 발견됐고, 새 로컬/Gemini 계약 테스트 4개가 실패했다. |
| Python 테스트 | `PYTHONUTF8=1 python -m pytest -q`: `300 passed, 1 skipped` (최종 실행 6.49초). 제거된 전용 테스트 때문에 총 개수가 줄었으며 품질 변화 지표가 아니다. |
| Ruff | `ruff check --output-format=github .` 및 `ruff format --check .` 통과. |
| 정적 검색 | `git grep -in -E`로 제거 대상 공급자 명칭, 모델 ID, SDK 패키지명과 전용 마운트 키를 검색한 결과 0건. |
| SVG | `xml.etree.ElementTree.parse('docs/infra-architecture-ppt.svg')` 통과. |
| 발표 화면 JS | `node --check presentation/static/presentation.js` 통과. |
| 로컬 온프레미스 변경 | 원래 작업 트리의 미추적 온프레미스 테스트에서 공급자 명칭 한 줄을 제거했고 `python -m pytest -q tests/test_onprem_compose.py`는 `4 passed`였다. 해당 사용자 변경은 이 PR에 포함하지 않는다. |
| Docker 런타임 | `docker compose config --quiet` 통과. `docker compose up -d`, `docker compose run --rm rag-api pytest -v`, `curl.exe --max-time 5 http://localhost:6333`, `docker compose run --rm rag-api python -m app.healthcheck`는 Docker Desktop Linux 엔진 named pipe가 없어 실패했다. |

## After / 관찰 결과

서버 답변 route는 Qwen과 Gemini 두 개이고 상태 응답에는 API·Ollama·Qdrant·Gemini만 남았다. Streamlit은 로컬/Gemini 두 패널을 표시한다. 발표 화면에서도 Gemini를 실시간 비교 경로로 사용하고 저장된 공급자 답변은 제공하지 않는다. 추적 파일에서 제거 대상 문자열은 0건이다.

검색 Recall, 답변 근거성, p95 지연시간, 운영 비용은 **측정하지 않음**. 이번 변경은 미사용 경로 제거이며 사용자 답변 품질 개선을 주장하지 않는다.

## 증거와 한계

- 설계: `docs/superpowers/specs/2026-09-18-retire-unused-aws-generation-design.md`; 계획: `docs/superpowers/plans/2026-09-18-retire-unused-aws-generation-implementation.md`.
- 구현 커밋: [`e9c29e1`](https://github.com/bbungjun/onpremis_rag_chatbot/commit/e9c29e1); 검토 PR: [#15](https://github.com/bbungjun/onpremis_rag_chatbot/pull/15).
- 기준선: `origin/main` (`d8ec28a`), Windows Python 3.11, 2026-09-18 (Asia/Seoul).
- Qwen/Gemini 실제 API 호출과 Docker 컨테이너 구동은 별도 런타임 조건이 필요하다. 이 작업의 테스트는 계약·로컬 동작을 확인한 것이다.
