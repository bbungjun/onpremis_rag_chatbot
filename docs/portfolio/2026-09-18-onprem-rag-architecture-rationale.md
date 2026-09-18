# 로컬 자가 호스팅 규정 RAG의 설계 근거 정리 (2026-09-18)

## Before / 문제

프로젝트의 README에는 RAG 파이프라인과 과거 평가 수치가 있었으나, 문서 규모·벡터 DB·HWP 파싱·청킹 단위를 선택한 이유가 로컬 추론의 비용·보안 목표와 연결되어 있지 않았다. “on-premise”라는 표현은 회사 사내망 서버를 운영하지 않는 현재 로컬 PC 시연과도 달랐다. 기본 Compose가 Qdrant/API/UI 포트를 호스트에 공개하고 `.env.example`이 Gemini 비교 기능을 켜며 팀 개발 설정은 원격 EC2 Ollama를 쓸 수 있는 상태에서, “사내 문서가 외부로 나가지 않는다”는 문장은 배포 검증 없이 보장할 수 없었다.

규모와 평가의 혼동도 있었다. 현재 기본 Markdown은 1개 파일·100개 조·600개 검색용 항이며, 합성 HWP 규정집은 1개 파일·8,000개 조·24,000개 항이다. 뒤의 수치는 생성·추출 검증 결과이고 대량 Qdrant 검색 결과는 아니다. 과거 50문항 검색 평가는 또 다른 해시의 작은 문서에서 수행됐다.

## Why / 분석과 대안

- 사용자 목표를 **로컬 자가 호스팅으로 외부 LLM API의 토큰별 요금을 피하고, 내부 문서의 외부 모델 전송 경계를 줄이는 것**으로 명확히 했다. 회사 사내망 서버는 사용자가 운영할 수 없으므로 현재 성과로 쓰지 않는다.
- 한 개의 “문서 규모” 숫자 대신 파일 바이트·정책/조/항 수·실제 벡터 수·갱신 비용·질의 부하를 분리했다. 합성 HWP의 압축 파일 크기만으로 대규모 검색을 주장하지 않는다.
- Qdrant는 현재 dense+sparse RRF와 규정 경로 필터에 맞는 구현 선택이다. pgvector와 Milvus는 공식 문서 기준의 대안으로 남기되, 동일 조건 DB 비교가 없다는 한계를 명시했다.
- 단일 HWP 변경 때 `--reset`은 전체 컬렉션을 지우고, `--reset`이 없으면 삭제된 조항의 오래된 포인트를 정리하지 않는 수집 경로를 확인했다. 대량 문서의 갱신 전략을 별도 설계 문제로 분리했다.
- 로컬 PC 시연, 자체 관리 GPU 클라우드 VM, 향후 회사 사내망 서버를 서로 다른 배포 형태로 구분했다. VM은 외부 LLM API와 다른 과금 구조지만 온프레미스는 아니다.

## Solution / 산출물

- [설계 근거](../RAG_ARCHITECTURE_RATIONALE.md): 제품 목표→현재 데이터 흐름→규모→Qdrant→HWP/청킹→보안·비용 경계→후속 검증 순서로 한 문서를 만들었다.
- [용어집](../../CONTEXT.md): 원본 문서, 규정집, 정책, 조, 항, 근거, 출처 참조를 구분한다.
- ADR 세 개: [로컬 추론](../adr/0001-local-inference-for-internal-policy-qa.md), [Qdrant](../adr/0002-qdrant-for-local-hybrid-retrieval.md), [조/항 청킹](../adr/0003-article-parent-clause-child-retrieval.md)의 변경 비용과 대안을 기록했다.
- README 첫 문단을 실제 배포 상태에 맞는 로컬 자가 호스팅 MVP로 정리하고 근거 문서를 연결했다. 런타임·데이터·평가 코드는 변경하지 않았다.

## Verification / 검증

- `origin/main` 커밋 `1019d97`을 기준으로 `app/chunking.py`, `app/document_reader.py`, `scripts/ingest_md.py`, `app/vector_store.py`, `app/rag_pipeline.py`, `app/qwen_client.py`, `docker-compose.yml`, `.env.example`의 진술을 대조했다.
- `datasets/docs/regulations.md`를 같은 코드의 `chunk_text`로 읽어 207,536바이트, 2,764줄, parent 100개, child 600개, 고유 ID 700개를 재확인했다. SHA-256은 `24e5ccdfd77863dc94c6d3af20ce0c25f6d8d49e2b4da3277089fa8558e060d2`다.
- 합성 HWP 1,000개 정책의 300,544바이트·8,000조·24,000항은 [선행 실험](2026-09-18-single-hwp-volume.md)의 생성·재추출 결과와 대조했다. SHA-256은 `c21b51d7191ca7d58df5d7141b7da50f6bfab3a1d28a80301009da732ad0de0a`다. 실제 Qdrant 포인트 수·지연은 측정하지 않았다.
- [50문항 검색 평가](2026-08-31-rrf-ablation-reranker-evaluation.md)의 문서 해시와 현재 기본 문서 해시가 다름을 확인했다. 검색 전략 효과를 벡터 DB 제품 우위나 대형 HWP 효과로 재해석하지 않았다.
- Qdrant/pgvector/Milvus의 공식 문서와 Qdrant 보안 안내, GPU VM 요금 페이지를 설계 대안의 출처로 사용했다. 변경 문서 8개의 로컬 상대 링크 검사에서 누락 0건이었다.
- Windows Python 3.11에서 `HWP_CLI_PATH`와 `PYTHONUTF8=1`을 설정한 `python -m pytest -q`: **321 passed, 1 skipped** (8.41초). `ruff check .`, `ruff format --check .`, `git diff --check`, `docker compose config --quiet`도 통과했다. 이는 문서 변경의 회귀 확인이지 사용자 가치 지표가 아니다.
- AGENTS.md의 `docker compose up -d`, `docker compose run --rm rag-api pytest -v`, `curl http://localhost:6333`, `docker compose run --rm rag-api python -m app.healthcheck`를 실행했으나 Docker Desktop Linux 엔진 named pipe가 없어 모두 런타임 검증으로 이어지지 못했다. 임시 `.env`는 `.env.example`에서 만들고 검증 후 제거했다.
- [PR #17](https://github.com/bbungjun/onpremis_rag_chatbot/pull/17)의 [GitHub Actions 실행](https://github.com/bbungjun/onpremis_rag_chatbot/actions/runs/35327035634)에서 lint와 test가 통과했다(초기 문서 커밋 `d797ecc`). CI는 Docker 런타임·비용·보안 검증을 대신하지 않는다.

## After / 결과

선택 이유와 대안, 현재 구현과 미병합 기능, 검증된 작은 문서와 아직 검색하지 않은 합성 HWP를 분리해 설명할 수 있게 됐다. 이는 **설계 설명의 명확성**에 대한 문서 변경이며 검색 Recall, 답변 품질, 보안성 또는 월 비용이 개선됐다는 측정은 아니다. 사용자가 문서만 읽고 다음 평가를 재현할 수 있도록 기준 데이터와 미측정 항목을 함께 기록했다.

## 증거와 한계

- 구현 전 설계: [설계 기록](../superpowers/specs/2026-09-18-onprem-rag-architecture-rationale-design.md). 코드 구현 계획은 필요하지 않은 문서 작업이다.
- 코드와 비교 대상은 병합된 main 기준이다. [HWP 서식 PR #16](https://github.com/bbungjun/onpremis_rag_chatbot/pull/16)은 이 문서 작성 시 열려 있었다.
- 역사적 검색 평가는 50개 held-out 질문, 문서 SHA-256 `4ecef7ee4a5a8b3eb1c6c1e23ad387618b85c2b382e3c97894a365932e9356cc`, Qdrant 1.18.2, RTX 3070 Ti 8GB, child 후보 20·parent top 5 조건이었다. 현재 기본 문서와 데이터가 같지 않다.
- 과거 Qwen 모델 전환 평가는 [prompt injection canary 유출 9/15](2026-09-06-think-mode-and-instruct-model.md)을 기록했다. 로컬 추론을 보안 완성으로 주장하지 않는 근거다.
- 실제 사내 문서, 실제 운영 사용자, HWP OCR 정확도, 대형 코퍼스 검색·색인, 원가 계산, 사내망 배포는 이번 문서 작업에서 측정하지 않았다. 로컬 작업 트리의 미커밋 시연 결과는 병합된 제품 상태로 취급하지 않는다.
