# llmenhance RAG 구현 학습 가이드

## 1. 이 문서의 목표

이 문서의 목표는 코드를 외우는 것이 아니라 현재 RAG 챗봇에서 질문 한 건이 처리되는
과정을 자신의 말로 설명하고, 설계 선택과 평가 결과를 면접에서 방어할 수 있게 하는
것이다.

학습이 끝나면 다음 문장을 세부 단계까지 풀어서 설명할 수 있어야 한다.

> 구조화된 사내 규정의 항(child)을 Dense와 BM25로 검색하고 RRF로 결합한 뒤,
> 검색된 항이 속한 조(parent) 전체를 Qwen에 제공하여 문서 근거 답변과 검색 출처를
> 반환한다.

## 2. 먼저 잡아야 할 전체 구조

프로젝트는 다섯 영역으로 나뉜다.

| 영역 | 책임 | 주요 파일 |
| --- | --- | --- |
| 문서 색인 | Markdown을 조·항으로 나누고 vector를 Qdrant에 저장 | `app/chunking.py`, `scripts/ingest_md.py` |
| 기본 RAG 실행 | 질문 해석, 검색, parent 확장, Qwen 답변 생성 | `app/rag_pipeline.py` |
| 외부 시스템 adapter | Ollama embedding/Qwen, Qdrant, Gemini, Bedrock 호출 | `app/embeddings.py`, `app/qwen_client.py`, `app/vector_store.py` |
| 실행 진입점 | CLI, FastAPI, Streamlit UI | `scripts/ask_rag.py`, `app/server.py`, `frontend/streamlit_app.py` |
| 평가 | 검색 전략 비교, ranking metric, reranker, Judge, report | `app/retrieval_*.py`, `app/reranker.py`, `app/local_judge.py` |

기본 제품 경로는 Ollama/Qwen이다. Gemini와 Bedrock은 비교·발표를 위한 별도 경로이며,
현재 MVP의 on-premise 핵심 경로와 혼동하지 않는다.

## 3. 두 개의 핵심 데이터 흐름

### 3.1 문서 색인 흐름

```text
datasets/docs/regulations.md
-> scripts/ingest_md.py
-> app/chunking.py
-> parent(조)와 child(항) 생성
-> child text를 bge-m3 dense vector로 변환
-> child text를 Kiwi/BM25 sparse vector로 변환
-> parent text와 구조 metadata를 payload에 포함
-> app/vector_store.py
-> Qdrant collection에 upsert
```

검색 대상은 child인 항 단위 텍스트다. parent인 조 전체는 직접 검색하기보다 child
payload의 `parent_text`로 보관하고, 검색 후 답변 context를 만들 때 사용한다.

### 3.2 질문 처리 흐름

```text
사용자 질문
-> scripts/ask_rag.py 또는 app/server.py
-> app/rag_pipeline.answer_question()
-> app/question_interpreter.py가 검색용 질문 생성
-> app/embeddings.py가 dense query vector 생성
-> app/sparse.py가 sparse query vector 생성
-> app/vector_store.py가 Qdrant hybrid RRF 검색
-> 검색 child를 parent 조로 확장하고 중복 제거
-> system prompt와 untrusted context/user data를 분리
-> app/qwen_client.py가 host Ollama/Qwen 호출
-> answer와 검색 기반 sources 반환
```

## 4. 권장 코드 학습 순서

### 4.1 `scripts/ask_rag.py`: 프로그램 시작점

먼저 CLI 인자와 `answer_question()` 호출만 확인한다. 세부 구현보다 사용자가 입력한
질문, `top_k`, metadata filter가 어디로 전달되는지 추적한다.

확인 질문:

- CLI에서 받은 질문은 어느 함수로 들어가는가?
- `--top-k`와 `--filter`는 어떤 값으로 전달되는가?
- timing callback은 어떤 단계의 시간을 출력하는가?

### 4.2 `app/rag_pipeline.py`: 전체 실행을 연결하는 orchestrator

처음에는 `answer_question()`만 읽는다. 한 줄씩 아래 책임에 표시한다.

1. 입력 검증
2. 질문 해석
3. Dense/Sparse 표현 생성
4. 검색
5. parent context 생성
6. Qwen 호출
7. answer/source 반환

그다음 `_expand_to_parents()`, `_build_context()`, `_build_user_prompt()`를 읽는다.

확인 질문:

- 검색 결과가 없을 때 Qwen을 호출하는가?
- 검색 `top_k`보다 더 많은 child를 먼저 가져오는 이유는 무엇인가?
- 여러 child가 같은 parent에 속하면 어떻게 중복 제거하는가?
- source는 Qwen이 생성하는가, pipeline이 생성하는가?
- system prompt와 user/context가 분리되어야 하는 이유는 무엇인가?

### 4.3 `app/question_interpreter.py`: 원본 질문과 검색 질문의 분리

다음 세 값의 역할을 구분한다.

- `original_question`: 사용자가 입력한 표현
- `canonical_question`: 규정 기준으로 해석한 질문
- `retrieval_question`: 검색 recall을 높이기 위한 질문

확인 질문:

- 이 해석은 LLM 기반인가, 규칙 기반인가?
- 상대 날짜나 연차 조건은 어떻게 정규화되는가?
- 질문 변환이 검색 품질을 높이는 대신 만들 수 있는 오류는 무엇인가?

### 4.4 `app/embeddings.py`와 `app/sparse.py`: 두 검색 표현

Dense와 Sparse를 다음처럼 비교한다.

| 항목 | Dense | Sparse/BM25 |
| --- | --- | --- |
| 중심 신호 | 문장의 의미적 유사성 | 토큰과 정확한 단어 일치 |
| 현재 구현 | Ollama `bge-m3` | Kiwi 토큰화와 sparse vector |
| 강한 예 | 표현이 다른 유사 질문 | 법인카드, 전표, 조항 번호 같은 핵심어 |
| 약점 | 고유명사·정확한 숫자를 놓칠 수 있음 | 다른 표현의 같은 의미를 놓칠 수 있음 |

확인 질문:

- `bge-m3`는 답변 생성 모델인가?
- 문서와 질문에 같은 embedding 모델을 써야 하는 이유는 무엇인가?
- BM25에서 문서 빈도가 낮은 단어가 중요한 이유는 무엇인가?
- 두 방식의 raw score를 직접 더하지 않는 이유는 무엇인가?

### 4.5 `app/vector_store.py`: Qdrant와 기본 hybrid 검색

다음 요소를 확인한다.

- named dense/sparse vector schema
- point와 payload 구조
- Dense와 sparse prefetch
- RRF fusion
- metadata filter
- 반환되는 score와 payload

확인 질문:

- vector와 payload의 차이는 무엇인가?
- payload에 `text`, `parent_text`, `parent_id`, `source_path`가 필요한 이유는 무엇인가?
- RRF가 서로 다른 점수 분포를 가진 검색 결과를 결합하기 좋은 이유는 무엇인가?
- metadata filter는 검색 전후 중 어느 단계에 적용되는가?

### 4.6 `app/chunking.py`와 `scripts/ingest_md.py`: 검색 데이터 생성

다음 구조를 실제 `regulations.md` 예시 하나와 연결한다.

```text
편 -> 장 -> 절 -> 조(parent) -> 항(child)
```

이후 parent 하나와 child 두 개가 어떤 dictionary로 만들어지고, Qdrant point payload에
어떻게 들어가는지 손으로 적어본다.

확인 질문:

- 문서를 고정 길이로 자르지 않고 규정 구조로 자르는 이유는 무엇인가?
- child 검색이 parent 검색보다 정밀할 수 있는 이유는 무엇인가?
- parent 전체를 context로 주는 이점과 token 비용은 무엇인가?
- 서로 다른 문서에 같은 `제1조`가 있으면 현재 ID 구조에서 어떤 문제가 생기는가?

### 4.7 `app/qwen_client.py`: 생성 모델 경계

다음을 확인한다.

- system message와 user message의 분리
- prompt injection guard
- Ollama `/api/chat` 요청 구조
- `temperature`, `num_ctx`, `num_predict`
- timeout과 오류 응답 처리

확인 질문:

- Qwen은 Qdrant를 직접 검색하는가?
- 검색 context를 신뢰할 수 없는 데이터로 취급하는 이유는 무엇인가?
- temperature를 낮게 설정한 이유는 무엇인가?
- source 목록과 답변 본문의 사실성이 별도로 검증되어야 하는 이유는 무엇인가?

### 4.8 `app/server.py`와 `frontend/streamlit_app.py`: 제품 경계

핵심 RAG를 이해한 다음 읽는다.

- FastAPI는 요청 validation과 provider별 pipeline 호출을 담당한다.
- Streamlit은 API를 호출하고 답변·source·상태를 화면에 표시한다.
- UI에 검색이나 생성 알고리즘이 들어 있지 않아야 한다.

확인 질문:

- `/health`와 `/health/services`의 차이는 무엇인가?
- API 입력의 `top_k`와 metadata filter에 어떤 제한이 필요한가?
- 인증이 없다면 내부 문서 서비스에서 어떤 문제가 발생하는가?

## 5. 반드시 이해해야 할 RAG 개념

### 5.1 Parent-child chunking

작은 child를 검색하면 질문과 직접 관련된 문장을 정밀하게 찾기 쉽다. 하지만 답변에
필요한 예외·조건이 이웃 항에 있을 수 있으므로, 검색 뒤에는 child가 속한 parent 조
전체를 context로 사용한다.

trade-off:

- 장점: 검색 정밀도와 답변 문맥을 동시에 확보
- 단점: parent가 길면 context budget과 생성 지연이 증가
- 위험: parent ID가 문서 범위에서 유일하지 않으면 다른 문서의 조항이 충돌

### 5.2 Dense 검색

질문과 문서의 의미를 vector 공간에서 비교한다. 표현이 달라도 의미가 가까운 문장을
찾을 수 있지만, 특정 용어·번호·희귀 토큰을 놓칠 수 있다.

### 5.3 BM25/Sparse 검색

질문과 문서에 등장하는 토큰의 일치와 희소성을 사용한다. 정책명, 증빙명, 조항 번호,
정확한 업무 용어를 찾는 데 강하지만 동의어와 문장 의미 변화에는 약하다.

### 5.4 RRF

Reciprocal Rank Fusion은 각 검색 방식의 raw score보다 순위를 이용한다. 검색 결과의
순위 `r`을 대략 `1 / (k + r)` 형태의 값으로 변환해 여러 목록의 점수를 합친다.

RRF를 쓰는 이유:

- cosine score와 BM25 score는 범위와 의미가 다르다.
- raw score normalization을 정교하게 맞추지 않아도 된다.
- Dense와 BM25 양쪽에서 높은 문서가 자연스럽게 위로 올라온다.

한계:

- 어떤 검색기를 더 신뢰할지 세밀하게 반영하기 어렵다.
- 잘못된 두 목록을 결합한다고 정답이 생기는 것은 아니다.
- `k`, candidate 수, parent collapse 순서가 결과에 영향을 준다.

### 5.5 Reranker

초기 검색으로 만든 candidate를 cross-encoder가 질문과 문서를 함께 읽고 다시
정렬한다. 보통 상위 순위 품질은 좋아질 수 있지만 추가 연산과 지연이 발생한다.

현재 프로젝트에서는 RRF 대비 reranker의 검색 MRR은 좋아졌지만 end-to-end source
recall, Judge 결과, 지연시간이 나빠졌다. 따라서 “최신 모델이므로 채택”하지 않고 전체
제품 결과를 기준으로 RRF를 유지했다.

## 6. 평가 지표 학습

### 6.1 Recall@k

정답 source 중 상위 k개 검색 결과 안에 들어온 비율이다. 정답이 하나인 현재 형태에서는
상위 k개 안에 정답이 있으면 1, 없으면 0으로 이해할 수 있다.

질문:

- Recall@5가 높고 Recall@1이 낮다면 사용자 경험에 어떤 영향이 있는가?
- context에 상위 3개만 들어간다면 Recall@5만 높아도 충분한가?

### 6.2 MRR@k

첫 정답의 순위에 역수를 적용한다.

```text
1위 정답 = 1
2위 정답 = 1/2
5위 정답 = 1/5
정답 없음 = 0
```

정답이 존재하는지만 아니라 얼마나 위에 배치됐는지 평가한다.

### 6.3 nDCG@k

여러 관련 문서가 있을 때 관련 문서가 위쪽에 잘 배치됐는지를 할인 누적으로 평가한다.
현재처럼 binary relevance를 쓰는 경우 gold source의 순위가 높을수록 값이 커진다.

### 6.4 절대 변화와 상대 변화

```text
Recall@5: 0.96 -> 1.00
절대 변화: +0.04 = +4%p
상대 변화: 0.04 / 0.96 = 약 +4.17%
```

`4% 향상`과 `4%p 향상`을 혼용하지 않는다.

### 6.5 Paired bootstrap CI

같은 질문을 두 검색 방식이 모두 평가했으므로 질문별 성능 차이를 짝으로 묶어
재표본추출한다. 이를 여러 번 반복해 평균 차이의 불확실성 구간을 구한다.

현재 50문항에서는 한 문항이 2%p다. 개선이 두 건뿐이고 CI 하한이 0이면 일반화된
우월성이 확정됐다고 말하면 안 된다.

### 6.6 Retrieval과 end-to-end의 분리

검색 지표가 좋아도 최종 답변이 반드시 좋아지는 것은 아니다.

```text
retrieval 평가:
정답 조항을 찾아 순위를 잘 매겼는가?

end-to-end 평가:
그 검색 결과로 Qwen이 정확하고 근거 있는 답변을 만들었는가?
```

reranker 기각 사례가 두 평가를 분리해야 하는 실제 근거다.

## 7. Grounding과 source를 구분하기

현재 source는 검색된 parent의 provenance다. 따라서 다음 두 문장은 서로 다르다.

```text
검색된 정답 source가 응답에 포함됐다.
답변의 모든 주장이 해당 source 원문에 의해 지지된다.
```

첫 번째는 source recall로 측정할 수 있다. 두 번째는 claim을 나누고 source 원문과
대조하는 entailment 또는 사람 평가가 필요하다.

또한 현재 fallback은 검색 결과가 없거나 context/답변이 비어 있을 때 동작하지만,
유사한 오답 문서가 검색됐을 때의 answerability를 보장하지 않는다. 따라서 무답 질문
평가가 별도로 필요하다.

## 8. 테스트를 활용한 학습법

각 모듈을 읽은 직후 대응 테스트를 읽는다.

| 구현 | 같이 읽을 테스트 |
| --- | --- |
| `app/chunking.py` | `tests/test_chunking.py` |
| `app/embeddings.py`, `app/qwen_client.py` | `tests/test_ollama_clients.py` |
| `app/sparse.py` | `tests/test_sparse.py` |
| `app/vector_store.py` | `tests/test_vector_store.py` |
| `app/rag_pipeline.py` | `tests/test_rag_pipeline.py` |
| `app/retrieval_search.py` | `tests/test_retrieval_search.py` |
| `app/retrieval_metrics.py` | `tests/test_retrieval_metrics.py` |
| `app/reranker.py` | `tests/test_reranker.py` |
| `app/local_judge.py` | `tests/test_local_judge.py` |

테스트에서 다음을 표시한다.

- Given: 어떤 입력과 mock 환경을 준비했는가?
- When: 어떤 공개 함수를 실행했는가?
- Then: 어떤 동작 계약을 검증하는가?
- 해당 테스트가 검증하지 않는 실제 runtime 위험은 무엇인가?

mock 테스트 통과는 외부 Ollama/Qdrant가 실제로 동작한다는 증거가 아니라는 점도
구분한다.

## 9. 추천 실습

### 실습 1: 질문 한 건 추적

질문을 하나 고정한다.

```text
연차 신청은 며칠 전까지 해야 하나요?
```

다음 값을 단계별로 출력하거나 debugger에서 확인한다.

1. original/canonical/retrieval question
2. Dense vector 차원
3. Sparse token과 index 일부
4. Qdrant child 검색 결과와 score
5. child의 `parent_id`
6. 중복 제거된 parent 목록
7. Qwen에 전달되는 system/user message
8. 최종 answer와 sources

### 실습 2: Dense와 BM25 차이 관찰

다음 유형을 각각 만들어 검색 결과를 비교한다.

- 문서와 표현은 다르지만 의미가 같은 질문
- 정확한 정책 용어가 포함된 질문
- 숫자 또는 조항 번호가 포함된 질문

### 실습 3: Parent expansion 확인

같은 조의 서로 다른 항이 상위 결과에 들어오도록 한 뒤, 최종 context에는 parent가
한 번만 포함되는지 확인한다.

### 실습 4: Fallback의 경계 확인

- 빈 질문
- Qdrant 결과 없음
- 문서와 무관한 질문
- 관련 단어는 있지만 정답은 없는 질문

각 경우에 Qwen 호출 여부와 fallback 결과가 어떻게 다른지 확인한다.

### 실습 5: 평가 수치 손계산

정답 ID 하나와 검색 결과 5개를 직접 만들고 Recall@1/3/5, MRR@5, nDCG@5를
손으로 계산한 뒤 코드 결과와 비교한다.

## 10. 면접에서 반드시 답할 질문

1. 고정 길이 chunking 대신 조·항 구조를 사용한 이유는 무엇인가?
2. 왜 child를 검색하고 parent를 생성 context로 사용하는가?
3. Dense와 BM25 중 하나만 선택하지 않은 이유는 무엇인가?
4. 서로 다른 score를 어떻게 결합하며 왜 RRF를 선택했는가?
5. Recall@5와 MRR@5는 어떻게 다르며 제품에 각각 어떤 의미가 있는가?
6. Dense 대비 RRF의 개선을 통계적으로 확정적이라고 말하지 않은 이유는 무엇인가?
7. reranker의 검색 순위가 좋아졌는데 왜 적용하지 않았는가?
8. source가 존재하면 답변이 grounded됐다고 볼 수 있는가?
9. 문서에 답이 없을 때 현재 구현은 어떤 경우에만 확실히 fallback하는가?
10. 서로 다른 규정집에 같은 제1조가 있으면 현재 구현에서 어떤 문제가 생기는가?
11. Qwen에 system prompt와 검색 context를 분리해서 전달하는 이유는 무엇인가?
12. 로컬/on-premise 구조에서 Qdrant와 Ollama는 각각 어디서 실행되는가?

각 질문에 대해 `설계 목적 -> 현재 구현 -> 검증 증거 -> 한계` 순서로 답한다.

## 11. 7일 학습 계획

### 1일차: 전체 query 흐름

- `ask_rag.py`와 `rag_pipeline.answer_question()` 읽기
- 질문 한 건의 sequence를 종이에 작성
- answer와 sources의 생성 주체 구분

### 2일차: 질문 표현과 검색

- `question_interpreter.py`, `embeddings.py`, `sparse.py` 읽기
- Dense/BM25 차이를 예시 세 개로 설명

### 3일차: Qdrant와 RRF

- `vector_store.py`, `retrieval_search.py` 읽기
- RRF 예제를 손으로 계산
- payload와 vector 역할 설명

### 4일차: Chunking과 ingestion

- `chunking.py`, `ingest_md.py`, `regulations.md` 함께 읽기
- parent/child point 예시를 직접 작성
- 다중 문서 ID 충돌 원인 설명

### 5일차: Prompt와 grounding

- `qwen_client.py`와 prompt 구성 함수 읽기
- injection guard, fallback, source 한계 설명
- 무답 질문 네 유형 작성

### 6일차: 평가

- `retrieval_metrics.py`, `retrieval_evaluation.py`, portfolio 결과 읽기
- Recall/MRR/nDCG와 CI 손계산
- reranker 기각을 2분 안에 설명

### 7일차: 통합 설명과 모의 면접

- 저장소 없이 3분 프로젝트 설명 녹화
- 면접 질문 12개에 답변
- 답하지 못한 내용만 코드와 artifact에서 재확인
- 추측한 수치는 모두 제거

## 12. 학습 완료 체크리스트

- [ ] 질문 한 건의 전체 경로를 파일 순서대로 설명할 수 있다.
- [ ] ingestion과 query 흐름을 혼동하지 않는다.
- [ ] Dense, BM25, RRF를 예시와 함께 설명할 수 있다.
- [ ] parent-child chunking의 장점과 비용을 설명할 수 있다.
- [ ] Qdrant point와 payload 구조를 설명할 수 있다.
- [ ] Qwen이 검색을 수행하지 않는다는 점을 설명할 수 있다.
- [ ] system/user/context 분리와 prompt injection guard의 목적을 설명할 수 있다.
- [ ] Recall@k, MRR@k, nDCG@k를 작은 예제로 계산할 수 있다.
- [ ] 절대 %p와 상대 % 변화를 구분할 수 있다.
- [ ] bootstrap CI 하한이 0인 결과를 과장하지 않는다.
- [ ] reranker를 기각한 근거를 retrieval과 E2E로 나누어 설명할 수 있다.
- [ ] source presence와 claim grounding을 구분할 수 있다.
- [ ] 현재 fallback과 다중 문서 ID의 한계를 설명할 수 있다.
- [ ] 모르는 수치를 추측하지 않고 재현 artifact에서 찾을 수 있다.

## 13. 관련 문서

- `README.md`: 실행 방법과 현재 아키텍처
- `docs/RAG_MVP_PLAN.md`: 초기 MVP 범위
- `docs/portfolio/2026-08-31-rrf-ablation-reranker-evaluation.md`: 최신 검색/E2E 결과
- `docs/superpowers/plans/2026-09-02-junior-rag-portfolio-readiness-roadmap.md`:
  제출 전 개선 로드맵

이 가이드를 끝까지 읽는 것보다, 각 단계에서 실제 입력과 출력을 한 번씩 직접 확인하는
것이 더 중요하다. 최종 목표는 구현을 암기하는 것이 아니라 설계 선택과 한계를 증거로
설명하는 것이다.
