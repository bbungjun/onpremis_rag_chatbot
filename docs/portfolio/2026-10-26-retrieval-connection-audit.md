# 복합 질문에서 검색된 연결 근거가 문맥 구성 중 누락되는 문제

실행일: 2026-10-26 (Asia/Seoul)

## 결론

현재 합성 규정집으로 만든 **목적 표집 복합 질문 12개**에서 필요한 정답 조문이
검색 child 후보 20개에는 모두 있었지만, 최종 생성용 문맥에는 9개 질문만
모든 정답 조문을 유지했다. 2개 질문은 문맥 길이 제한으로, 1개 질문은
상위 parent 5개를 고르는 단계에서 필요한 조문이 제외됐다.

이는 답변 정확도나 GraphRAG의 개선 효과가 아니다. Qwen 답변과 Judge는
호출하지 않았다. 현재 서버가 아닌 Qdrant Local 메모리 재구축 진단 결과다.

## Before / 문제

GraphRAG 도입 전에 기존 검색이 놓치는 연결이 무엇인지 확인할 필요가 있었다.
기존 `qa_set.jsonl`의 50문항 중 복수 정답 조항 질문은 1개이며,
`qa_holdout.jsonl`의 50문항은 모두 단일 정답 조항이었다. 이 데이터만으로는
여러 조문을 연결해야 하는 직원 질문의 근거 충족을 평가할 수 없었다.

과거 2026-08-31 검색/생성 산출물을 대조해 추가 점검 대상도 찾았다.
`h14`는 정답 조문이 검색 parent 4번째였지만 최종 반환 출처에 없었고,
`h19`는 정답 조문이 검색 1번째였지만 반환 출처가 비어 있었다.
두 파일은 단계 전체를 함께 계측한 하나의 실행이 아니므로, 이 대조만으로
문맥 잘림 또는 생성 실패를 원인으로 확정하지 않았다. 당시 문서 해시도
현재 문서와 달라 과거 결과와 이번 진단을 Before/After로 비교하지 않는다.

## Why / 원인 분리

1. **원문 부재:** 필요한 사실을 문서에서 찾을 수 없는 문제
2. **후보 누락:** 검색 child 20개에 정답 조문의 child가 없는 문제
3. **parent 선택 누락:** 후보에는 있지만 고유 parent 상위 5개에서 제외되는 문제
4. **문맥 누락:** 선택한 parent가 길이 예산 때문에 통째로 제외되는 문제
5. **생성 실패:** 근거 전달 이후 모델이 답하지 못하는 문제

이번 진단은 2~4번을 같은 실행에서 계측했다. 정답 조문은 원문을 읽고
질문의 각 요구 사항에 대응시켜 사전에 고정했다. 단지 다른 조문을 참조한다는
이유로 모든 참조 조문을 정답에 포함하지 않았다. 원문 사실 자체의 독립 검수와
답변 품질 평가는 수행하지 않았다.

문서 구조 검사에서는 조문 100개, child 600개, 내부 유향 연결 139개를 확인했다.
81개 조문에 하나 이상의 내부 참조가 있었다. 외부 법률 참조 8개는 제외했다.
법률과 내부 규정에 같은 조항 번호가 있다는 이유로 두 조문을 연결하면 안 된다.
이 검사는 명시적 참조의 규칙 기반 추출이며, 의미 관계 전체를 추출한 것이 아니다.

## Solution / 진단 도구

- [사전 설계](../superpowers/specs/2026-10-26-retrieval-connection-audit-design.md)에
  진단 범위와 단계별 측정을 기록했다.
- [진단 데이터](../../datasets/eval/connection_diagnostic.jsonl)에 복합 질문 12개와
  단일 조문 대조 질문 4개의 정답 조항 및 요구 사항을 검색 실행 전에 고정했다.
- [진단 스크립트](../../scripts/audit_retrieval_connections.py)는 현재 문서를
  호스트 Ollama의 bge-m3로 임베딩하고, 격리된 Qdrant Local 메모리 컬렉션에 적재했다.
- 제품의 `search_chunks`, 질문 해석, parent 선택, 문맥 조립 함수를 사용했다.
  Qdrant 클라이언트의 생성 대상만 진단 프로세스 안에서 메모리 클라이언트로 바꿨다.
- 정답 조문의 단계별 포함 여부와 최초 누락 단계, 참조 그래프상의 도달 거리를 기록했다.
  도달 거리는 그래프 확장을 실제 적용한 검색 성능이 아니다.
- 제품 검색, 생성 프롬프트, Qwen 모델 및 서비스 인덱스는 변경하지 않았다.

## After / 관측 결과

각 숫자는 해당 단계에 **필요한 모든 정답 조문이 포함된 질문 수**다.
정답 조문의 일부만 검색된 경우는 성공으로 세지 않았다.

| 진단군 | 질문 수 | child 후보 20개 | parent 최대 5개 | 최종 문맥 |
|---|---:|---:|---:|---:|
| 복합 질문 | 12 | 12/12 | 11/12 | 9/12 |
| 단일 조문 대조 질문 | 4 | 4/4 | 4/4 | 4/4 |

복합 질문의 단계 간 근거 충족 비율은 100% → 91.7% → 75%였다.
이는 동일 파이프라인 내부의 관측치이며 변경 전후의 개선률이 아니다.
최종 문맥에서 필요한 조문이 빠진 사례는 다음과 같다.

| ID | 질문의 요구 사항 | 누락된 연결 | 최초 누락 단계 | 관측 내용 |
|---|---|---|---|---|
| m01 | 국내 출장 숙박비·정산 기한·적격 증빙 | 정산 제82조 → 증빙 제64조 | 문맥 조립 | 제64조가 parent 4번째에 있었으나 최종 문맥은 제80·82·81조만 유지 |
| m03 | 원격지 전근 발령·부임 여비의 숙박 기준 | 전근 제19조 → 출장비 제80조 | 문맥 조립 | 제80조가 parent 4번째에 있었으나 최종 문맥은 제19·22·13조만 유지 |
| m07 | 재택근무 적용 대상·접속 인증·기록 보관 | 접속 제85조 → 재택근무 제37조 | parent 선택 | 제37조가 후보 내 고유 parent 순서 8번째라 상위 5개에서 제외 |

세 누락 조문 모두 최종 문맥에 남은 조문에서 명시적 참조 한 단계로 도달 가능했다.
하지만 세 조문은 이미 기존 검색 후보에도 있었다. 따라서 이번 결과는 새 문서를
찾아오는 전면 GraphRAG 전환보다, **명시적 연결과 질문별 요구 사항을 반영한
근거 선택 및 문맥 보존**을 먼저 실험해야 한다는 판단을 뒷받침한다.
누락 조문을 문맥 뒤에 단순히 추가하면 기존 길이 제한으로 다시 제외될 수 있다.

나머지 복합 질문 m02·m04·m05·m06·m08·m09·m10·m11·m12와 대조 질문
c01~c04는 필요한 모든 조문을 최종 문맥에 유지했다. 원본 결과에 성공과 실패를
모두 보존했다. 문맥 예산 초과는 이번 16건에서 0건이었다.

## Verification / 재현 및 검증

원래 작업 디렉터리에서 실행한 명령:

```powershell
$env:PYTHONUTF8='1'
$env:PYTHONIOENCODING='utf-8'
python scripts/audit_retrieval_connections.py --output reports/retrieval-eval/connections-20261026-local-01
python -m pytest -q
```

- 진단 도구 테스트: 구현 전 import 실패를 확인한 뒤 구현 후 3개 통과.
- 원래 작업 디렉터리 전체 테스트: **363 passed, 1 skipped**.
- 첫 로컬 전체 테스트는 Windows cp949의 subprocess 출력 디코딩 오류로
  1 failed, 362 passed, 1 skipped였다. 코드 수정 없이 `PYTHONUTF8=1`로 재실행했다.
- 게시용 격리 브랜치의 전체 테스트: **341 passed, 9 skipped**.
  원래 디렉터리의 미추적 파일 및 별도 브랜치 작업이 있어 두 테스트 집합은 다르다.
- `python -m ruff check scripts/audit_retrieval_connections.py tests/test_connection_audit.py` 통과.
- `python -m ruff format --check scripts/audit_retrieval_connections.py tests/test_connection_audit.py` 통과.

AGENTS.md의 필수 서버 검증도 시도했으나 다음과 같이 완료하지 못했다.

| 명령 | 결과 |
|---|---|
| `docker compose up -d` | Docker 시작 오류로 응답하지 않아 중단 |
| `docker compose run --rm rag-api pytest -v` | 같은 원인으로 실행 차단 |
| `curl.exe --max-time 5 http://localhost:6333` | 연결 실패, exit 7 |
| `docker compose run --rm rag-api python -m app.healthcheck` | 같은 원인으로 실행 차단 |

Docker backend 로그에서 Inference manager의 `dockerInference` 소켓 초기화 실패를
확인했다. 초기화·볼륨 삭제 등 복구 작업은 수행하지 않았다.

## 실행 조건과 증거

- 원래 소스: `feat/intent-classification-accuracy`, HEAD
  `e2b00943e519ad951e94cb3d627b8e0ccfea1982` 및 기존 사용자 변경 상태.
  실제 실행 파일별 해시는 `run.json`에 기록했다.
- 게시 브랜치는 `origin/main`의 `f970ee8af4e97dba041e2184189faaebf6b72b41` 기준이다.
  이 버전은 parent 중복 제거의 문서 구분과 청킹 처리가 일부 다르다.
  이번 단일 문서에서 저장된 16개 검색 결과를 main의 질문 해석·parent 선택·문맥 조립에
  재생했으며, 검색 질문·parent ID·문맥 ID·프롬프트 길이가 모두 일치했다.
  이 검증은 main에서 검색을 다시 실행했다는 의미가 아니다.
- PC: Intel Core i5-13600KF, NVIDIA GeForce RTX 3070 Ti 8,192 MiB.
- Ollama 0.32.5, `bge-m3:latest`, F16, embedding dimension 1024.
- 모델 digest: `7907646426070047a77226ac3e684fbbe8410524f7b4a74d02837e43f2146bab`.
- Qdrant Local client 1.18.0, kiwipiepy 0.23.2, dense cosine + sparse IDF + RRF.
- top_k=5, child 후보=20, metadata filter 없음.
- NUM_CTX=4096, 기존 코드의 프롬프트 문자 예산=3891.
  토큰 수를 직접 측정한 예산이 아니다.
- 수집 임베딩은 16개씩 배치 호출했고, 질문 임베딩은 제품의 단일 요청 함수를 사용했다.
- 문서 SHA-256: `24e5ccdfd77863dc94c6d3af20ce0c25f6d8d49e2b4da3277089fa8558e060d2`.
- 진단 데이터 SHA-256: `8c701a13c90b9357b682623d5e99351f607a65853e165fe46dc8b19ede965b29`.
- 원본 결과 SHA-256: `5e63a0f0be85de5612ad0cdd4455f6cc0c653b1bf21b9c9a442d661ebcbd5aea`.
- 로컬 산출물: `reports/retrieval-eval/connections-20261026-local-01/`의
  `run.json`, `frozen_cases.json`, `links.json`, `results.jsonl`, `summary.json`,
  `required_checks.json`, `main_replay.json`, `verify_replay.py`.
  실행 원본은 git에서 제외되며 원래 작업 디렉터리와 게시용 worktree에 보존했다.
  main 재생 검증 산출물 두 개는 게시용 worktree에 보존했다.

## 한계와 다음 실험

- 문서를 읽고 만든 작은 진단 세트이므로 실제 직원 질문 분포를 대표하지 않는다.
  정답 지정은 에이전트의 문서 검토 결과이며 사람의 독립 라벨 검수는 없다.
- 조문 ID 포함은 요구한 사실이 답변에 정확히 사용됐음을 보장하지 않는다.
  답변 정확도, 환각, 인젝션 방어, 실제 응답 지연 및 운영 품질은 **측정하지 않음**.
- Qdrant Local의 정확 검색과 실제 서버의 인덱스·근사 검색 결과는 다를 수 있다.
  현재 서비스 인덱스의 내용·정합성과 같은 결과를 보장하지 않는다.
- GraphRAG 패키지, 관계 확장, 재정렬 또는 문맥 압축의 효과는 **측정하지 않음**.
- 다음 실험은 먼저 별도의 development 질문으로 참조 관계를 고려한 근거 선택과
  필요한 항 중심의 문맥 구성을 설계하고, 동일 조건의 기존 방식과 비교한다.
  이번 진단 데이터를 수정·튜닝에 사용하면 최종 검증에는 새로 분리한 질문이 필요하다.
- 현 단계에서 사용자 가치 개선이나 이력서용 성능 개선 수치는 주장하지 않는다.
