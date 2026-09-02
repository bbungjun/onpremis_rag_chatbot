# 신입 AI/RAG 포트폴리오 제출 준비 로드맵

## 목적

현재 프로젝트는 구조 기반 청킹, Dense+BM25 RRF 검색, parent 확장, 출처 반환,
held-out 평가와 reranker 비교까지 구현한 강한 RAG MVP다. 그러나 포트폴리오 제출
관점에서는 구현의 깊이보다 다음 세 문제가 더 큰 위험이다.

1. 핵심 설계와 평가 수치를 작성자가 면접에서 설명하기 어렵다.
2. 최신 평가 결과의 원시 실행 증거가 로컬에만 있고 제출 가능한 형태로 정리되지 않았다.
3. 답변 거절, claim-level grounding, 다중 문서 처리가 충분히 검증되지 않았다.

이 문서는 아래 여섯 작업을 프로젝트의 공식 후속 로드맵으로 보존한다. 각 작업은
코드 변경만으로 완료되지 않으며, 같은 조건에서 재현 가능한 검증과 포트폴리오 문서
갱신까지 끝나야 완료로 간주한다.

## 현재 기준선

- 목표 직무: 신입·주니어 AI/RAG 엔지니어
- 현재 강점: 구조 기반 parent-child 검색, Dense/BM25/RRF 비교, held-out 평가,
  검색 지표와 end-to-end 결과를 함께 고려한 reranker 기각
- 현재 테스트 상태: `267 passed, 1 skipped, 2 failed`
- 알려진 테스트 실패: 공유 EC2 URL placeholder와 agent setup 계약 테스트의 기대값 불일치
- 최신 평가 코드·데이터·문서 중 다수가 아직 미추적 상태
- 원시 평가 결과는 로컬에 있으나 비민감 재현 artifact로 정리되지 않음
- 현재 결과는 단일 합성 규정집을 중심으로 측정됨

이 기준선은 작업 시작 시 다시 측정한다. 과거 수치를 새로운 실행 결과처럼 사용하지
않고, 실행 날짜·데이터셋 hash·문서 hash·모델·설정·하드웨어를 함께 기록한다.

## 실행 순서와 의존성

```text
1. 설명 가능성 확보
        |
        v
2. 평가 artifact 및 단일 재생성 명령
        |
        v
3. 작업 트리 정리, 테스트 복구, 제출 커밋
        |
        +-------------------+
        v                   v
4. 무답·공격 평가       6. 다중 문서 ID 및 검증
        |                   |
        +---------+---------+
                  v
        5. claim-source grounding 평가
                  |
                  v
        최종 포트폴리오 문서 및 제출 태그
```

1~3은 포트폴리오 신뢰성의 선행 조건이다. 4와 6은 파일 소유권이 겹치지 않는 범위에서
병렬로 진행할 수 있다. 5는 무답·공격 사례와 다중 문서 source가 안정된 뒤 수행한다.

## 1. 핵심 설계와 수치를 코드 없이 설명 가능하게 만들기

### 목표

면접에서 코드를 열지 않고도 RRF, parent expansion, 평가 지표, reranker 기각을
자신의 말로 설명하고 후속 질문에 답할 수 있게 한다.

### 반드시 설명할 내용

- Dense와 BM25가 각각 잘 찾는 질문 유형과 한계
- RRF가 서로 다른 점수 체계를 순위 기반으로 결합하는 이유
- 항(child)을 검색하고 조(parent)를 LLM 문맥으로 확장하는 이유와 trade-off
- Recall@1/3/5, MRR@5, nDCG@5가 각각 측정하는 것
- `0.96 -> 1.00`이 절대 `4%p`, 상대 약 `4.17%` 개선인 이유
- 50문항에서는 한 문제가 `2%p`이며 bootstrap CI 하한이 0일 때 과장하면 안 되는 이유
- reranker가 MRR을 높였는데도 출처 Recall, Judge 점수, 지연시간 때문에 기각된 이유
- source presence/source recall과 claim grounding이 서로 다른 이유

### 산출물

- 면접용 3분 설명문
- 개념별 한 문장 정의와 예상 꼬리 질문
- 화이트보드용 RAG 데이터 흐름 한 장
- 현재 실험 수치의 출처를 연결한 표

### 완료 조건

- 저장소나 메모를 보지 않고 3분 설명을 녹화한다.
- 다른 사람이 위 네 주제에서 최소 10개 꼬리 질문을 하고 답변을 검토한다.
- 답하지 못한 항목은 코드와 원시 결과로 확인한 뒤 설명문을 수정한다.
- 수치를 기억하지 못할 때 추측하지 않고 어떤 artifact에서 확인할지 설명할 수 있다.

## 2. 비민감 평가 artifact와 단일 재생성 명령 만들기

### 목표

비밀·사내 원문·개인정보를 포함하지 않으면서 제3자가 포트폴리오의 집계 수치를
독립적으로 다시 계산할 수 있게 한다.

### 구현 원칙

- 원시 질문·답변·문서 본문처럼 민감할 수 있는 값은 기본적으로 Git에서 제외한다.
- 추적 artifact에는 run 설정, hash, case ID, gold source ID, predicted source ID,
  ranking position, latency, fallback 여부, metric 집계에 필요한 최소 값만 둔다.
- 비밀값, 환경 변수 원문, endpoint, 자격증명, 내부 정책 원문은 저장하지 않는다.
- artifact schema와 익명화/제외 규칙을 테스트로 고정한다.
- 집계 문서는 artifact에서 생성하며 사람이 숫자를 복사해 덮어쓰지 않는다.

### 단일 명령 계약

최종 명령 하나가 추적 가능한 sanitized artifact를 읽어 다음을 재생성해야 한다.

```text
- Recall@k, MRR@k, nDCG@k
- paired difference와 bootstrap CI
- 평균/P50/P95 latency
- fallback, source return, source recall
- 방법별 비교 Markdown 또는 HTML 요약
```

정확한 명령과 출력 경로는 구현 시 확정하고 README와 포트폴리오 문서에 기록한다.

### 완료 조건

- 깨끗한 checkout에서 단일 명령이 네트워크와 LLM 호출 없이 집계를 재생성한다.
- 생성된 값이 채택된 실행의 요약과 일치한다.
- 데이터셋·문서·모델·설정·실행일·하드웨어 metadata가 함께 출력된다.
- secret scan과 artifact schema 테스트가 통과한다.
- 결과가 없거나 불완전하면 성공으로 종료하지 않는다.

## 3. 작업 트리 정리, 실패 테스트 복구, 제출 커밋 만들기

### 목표

최신 기능과 평가 증거를 검토 가능한 커밋으로 만들고, 전체 테스트가 통과하는
재현 가능한 포트폴리오 기준점을 만든다.

### 작업 순서

1. `git status --short --branch`로 기존 변경과 새 변경을 분류한다.
2. 미추적 평가 코드·테스트·데이터·설계·포트폴리오 문서를 기능 단위로 검토한다.
3. 공유 EC2 placeholder와 setup contract 사이의 올바른 계약을 결정한다.
4. 테스트를 먼저 수정하거나 추가한 뒤 최소한의 구현/문서 변경으로 두 실패를 해결한다.
5. 각 변경 파일의 `git diff`를 개별 검토한다.
6. `git diff --check`와 관련 검증을 실행한다.
7. 관련 파일만 stage하고 의미 있는 단위로 commit한다.

### 완료 조건

- 전체 테스트가 실패 없이 통과한다. skip은 사유와 실행 조건을 문서화한다.
- Docker, Qdrant, Ollama가 필요한 검증은 실제 런타임 조건에서 별도로 기록한다.
- 최신 평가 코드·데이터·문서가 추적 상태다.
- 제출 기준 커밋 hash와 재현 명령이 포트폴리오 문서에 기록된다.
- 원래 사용자의 관련 없는 변경은 commit에 포함하지 않는다.

## 4. 무답 질문과 공격 질문 평가 세트 추가하기

### 목표

문서가 답을 확인하지 못할 때 안전하게 거절하고, 사용자 입력이나 검색 문맥의 공격
지시를 따르지 않는다는 것을 실제 end-to-end 실행으로 검증한다.

### 데이터셋 범주

- 문서 범위 밖 질문
- 관련 용어는 있지만 정답이 없는 질문
- 일부 조건만 문서에 있는 질문
- 존재하지 않는 조항·절차를 전제한 질문
- 사용자가 시스템 지침 무시를 요구하는 공격
- 검색 문서 안에 삽입된 prompt injection
- source를 조작하거나 존재하지 않는 근거를 출력하라는 공격

### 측정 항목

- 적절한 거절률과 잘못된 거절률
- 문서에 없는 내용을 확정적으로 답한 비율
- 공격 지시 준수율
- 존재하지 않는 source 생성률
- 거절 답변의 일관성과 유용성

### 완료 조건

- answerable/partially answerable/unanswerable/adversarial label 기준이 문서화된다.
- 개발용과 held-out 공격 세트를 분리한다.
- 실제 Qwen 경로에서 같은 설정으로 평가한다.
- 실패 사례를 삭제하지 않고 원인과 함께 보존한다.
- 목표 기준은 사전에 정의하며 결과를 본 뒤 낮추지 않는다.

## 5. 답변 주장과 출처 원문 간 grounding 평가 추가하기

### 목표

검색된 source ID가 반환됐다는 사실을 넘어, 답변의 개별 사실 주장이 실제 source
본문에서 지지되는지 평가한다.

### 권장 접근

1. 답변을 검증 가능한 원자적 claim으로 분해한다.
2. 각 claim에 근거 source 조항을 연결한다.
3. source 원문을 포함해 `supported`, `contradicted`, `not enough information`으로 판정한다.
4. 자동 Judge와 블라인드 사람 평가의 일치도를 별도로 기록한다.
5. 전체 답변 단위로 unsupported claim rate와 citation precision/recall을 집계한다.

Judge에게는 질문·reference answer·candidate answer·source ID만 전달하지 말고, 실제로
검색된 source 본문을 제공한다. 사람 평가자는 방법명을 모르는 상태에서 같은 rubric을
사용한다.

### 완료 조건

- rubric과 예시, 경계 사례가 문서화된다.
- 최소 두 명의 독립 평가자가 일부 표본을 검토한다.
- 평가자 간 일치도와 불일치 해결 절차를 기록한다.
- 자동 Judge 점수를 사람 정확도로 표현하지 않는다.
- unsupported claim과 잘못된 citation 사례를 포트폴리오에 포함한다.

## 6. 다중 문서 parent ID 충돌 해결 및 검증하기

### 목표

서로 다른 문서에 같은 조 번호가 있을 때 parent가 합쳐지거나 누락되지 않도록 문서
범위의 안정적인 식별자를 사용한다.

### 설계 방향

- `parent_id`를 조 번호만으로 만들지 않는다.
- 최소한 정규화한 `document_id + article_id` 조합을 사용한다.
- source path 변경과 문서 개정 시 ID 안정성/재색인 정책을 명시한다.
- point ID, payload parent ID, parent collapse, source 출력이 같은 식별자 계약을 쓴다.
- 기존 단일 문서 index의 migration 또는 clean reindex 요구사항을 기록한다.

### 검증 corpus

최소 두 개의 구조화 문서를 사용하고 두 문서 모두에 `제1조`, `제2조`처럼 동일한
조 번호를 포함한다. 질문별 gold source가 서로 다른 문서를 가리키는 사례와 두 문서를
동시에 참조해야 하는 사례를 포함한다.

### 완료 조건

- 동일 조 번호를 가진 두 parent가 ingestion 후 각각 존재한다.
- 검색과 parent collapse에서 어느 문서도 누락되거나 합쳐지지 않는다.
- source path와 parent ID가 올바른 문서를 가리킨다.
- reset 및 일반 upsert 경로를 모두 검증한다.
- 기존 단일 문서 회귀 테스트와 새 다중 문서 end-to-end 테스트가 통과한다.

## 최종 포트폴리오 제출 게이트

다음 조건을 모두 충족해야 이 로드맵을 완료로 표시한다.

- 1~6 각 항목의 완료 조건과 실패 사례가 문서화됨
- 동일 조건의 Before/After 결과가 존재함
- 전체 테스트, 정적 검사, Docker/Qdrant/healthcheck 검증 결과가 기록됨
- 비민감 평가 artifact에서 핵심 표를 단일 명령으로 재생성 가능함
- 제출 commit과 dataset/document hash가 기록됨
- 합성 데이터, 작은 표본, Judge 한계, 미측정 운영 항목을 명시함
- 이력서 문구가 실제 측정 범위를 넘지 않음

필수 검증 명령의 기준은 다음과 같다.

```powershell
docker compose up -d
docker compose run --rm rag-api pytest -v
curl.exe http://localhost:6333
docker compose run --rm rag-api python -m app.healthcheck
git status --short --branch
git diff --check
```

각 구현 작업이 끝날 때 `docs/portfolio/<YYYY-MM-DD>-<topic>.md`를 갱신하거나 새로
작성한다. 실행할 수 없었던 검증은 성공으로 간주하지 않고 blocker와 `not measured`를
명시한다.
