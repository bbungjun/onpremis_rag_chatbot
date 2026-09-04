# RRF Ablation and Local Reranker Evaluation Design

## 문서 목적

이 문서는 GitHub 이슈 #1의 검색 실험을 재현 가능한 평가 시스템으로 구체화한다.
현재 RAG 파이프라인의 76문항 결과는 전체 시스템 성능을 보여주지만, dense 검색,
BM25 검색, RRF 결합 각각의 기여도를 분리하지 못한다. 따라서 기존 결과를 RRF의
개선 효과라고 주장하지 않고, 동일 조건의 paired ablation으로 Before/After를 새로
측정한다.

최종 목표는 다음 두 질문에 근거 있는 답을 만드는 것이다.

1. Dense-only 대비 BM25와 RRF가 정답 조항 검색에 얼마만큼 기여하는가?
2. 기본 RRF 이후 Weighted RRF, DBSF 또는 로컬 reranker가 추가 품질 향상을 만드는가?

## 현재 기준선

현재 제품 검색 경로는 다음과 같다.

```text
사용자 질문
  -> 결정적 질문 해석 및 retrieval_question 생성
  -> bge-m3 dense embedding
  -> kiwipiepy 기반 BM25 sparse vector
  -> Qdrant dense + sparse RRF 검색
  -> 요청 top_k의 4배만큼 child(항) 후보 조회
  -> parent_id 기준 중복 제거
  -> 상위 top_k parent(조) 원문으로 확장
  -> Qwen 답변 생성
  -> answer + parent-level sources 반환
```

기존 76문항 단일 실행에서는 핵심 답변 정답률 93.4%, 정답 조항 Recall@5
92.1%, 평균 응답 시간 14.57초를 기록했다. 이 값은 과거 전체 RAG 실행의 참고값일
뿐이며, 본 실험의 Before나 After로 재사용하지 않는다. 비교 실험은 동일 실행에서
모든 검색 방식을 다시 측정한다.

## 설계 원칙

- 검색 품질과 답변 생성 품질을 분리한다.
- 모든 검색 방식은 동일한 질문 해석 결과, Qdrant 컬렉션, 문서 버전, top-k,
  candidate limit 및 parent collapse 규칙을 사용한다.
- 개발셋에서 선택하거나 튜닝한 설정을 held-out 결과에 맞춰 다시 변경하지 않는다.
- RRF는 기존 제품 기본값으로 유지한다. 실험 결과가 나오기 전에 운영 검색 방식을
  교체하지 않는다.
- Qwen은 RAG 답변 생성에만 사용한다. 검색 점수 계산, fusion, reranking 또는 평가
  레이블 생성에 Qwen을 사용하지 않는다.
- Reranker를 포함한 모든 후보는 로컬에서 실행 가능해야 하며 외부 API를 요구하지
  않는다.
- 검색된 문서와 사용자 질문은 계속 신뢰할 수 없는 데이터로 취급한다. 본 실험은
  기존 system/user prompt 분리와 prompt injection guard를 변경하지 않는다.
- 원시 질문, 검색 문서 및 생성 답변을 포함하는 실행 결과는 Git에 커밋하지 않는다.

## 범위

### 포함

- Dense-only, BM25-only, 기본 RRF 비교
- Weighted RRF와 DBSF 비교
- 기본 RRF 후보에 대한 `BAAI/bge-reranker-v2-m3` 재정렬 비교
- parent 조항 기준 Recall@1/3/5, MRR@5, nDCG@5 계산
- query representation, Qdrant search, fusion, reranking latency 분리 측정
- 개발셋과 held-out 평가셋의 분리
- 질문별 JSONL, 실행 메타데이터, 집계 Markdown 보고서 생성
- 최종 후보에 한한 Qwen end-to-end 답변 평가

### 제외

- Qwen 모델 교체 또는 파인튜닝
- BGE-M3 임베딩 모델 파인튜닝
- SPLADE, ColBERT 또는 BGE-M3 learned sparse의 동시 도입
- LLM 기반 query rewriting
- 자연어-to-SQL 또는 별도 관계형 데이터베이스
- 평가 결과가 나오기 전 운영 기본 검색 방식 변경
- 현재 50문항 개발셋 결과를 최종 이력서 성과로 발표하는 것

## 평가 데이터 설계

### 개발셋

`datasets/eval/qa_set.jsonl`의 현재 50문항을 개발셋으로 사용한다.

- 전부 직원이 묻는 한국어 자연어 정책 질문이다.
- 각 레코드는 `id`, `type`, `question`, `gold_jo`, `answer`를 가진다.
- 이 데이터는 기존 실패 분석과 질문 해석 설계에 이미 사용됐으므로 최종 성과
  측정용으로 간주하지 않는다.
- Weighted RRF 가중치, DBSF 채택 여부, reranker candidate limit 및 batch 설정은
  이 개발셋에서만 선택한다.

기존 설계와 달리 조항 번호를 직접 묻는 별도 유형은 만들지 않는다. 제품 대상은
규정 번호를 아는 사용자가 아니라 실무 질문을 하는 직원이기 때문이다.

### Held-out 평가셋

최종 비교를 위해 `datasets/eval/qa_holdout.jsonl`에 새로운 자연어 정책 질문
50문항을 만든다.

- 현재 개발셋과 문장만 바꾼 단순 중복 질문을 금지한다.
- 연차, 재택근무, 출장비, 경비 증빙, 개인정보, 보안, 결재, 계약 등 실제 제품
  영역을 고르게 포함한다.
- 모든 질문은 `datasets/docs/regulations.md`만으로 답할 수 있어야 한다.
- `gold_jo`는 답에 필요한 모든 parent 조항을 포함한다.
- 평가셋 작성 후 SHA-256을 기록하고 fusion 또는 reranker 설정을 더 이상 변경하지
  않는다.
- held-out은 최종 설정으로 한 번 실행한다. 오류 수정으로 재실행할 경우 코드,
  설정, 데이터 해시와 재실행 사유를 새 run 메타데이터에 남긴다.

50문항에서는 질문 한 건이 2%p이므로 작은 차이를 과장하지 않는다. 최종 보고서는
평균 차이뿐 아니라 질문별 paired 결과와 bootstrap 95% 신뢰구간을 함께 제시한다.

## 비교 검색 방식

모든 방식은 `retrieval_question`을 입력으로 받고 child 검색 결과를 반환한다.

### A. Dense-only

- Query: `bge-m3` dense vector
- Qdrant vector: `dense`
- Distance: cosine
- Sparse representation은 만들 수 있지만 검색 점수에는 사용하지 않는다.

### B. BM25-only

- Query: `kiwipiepy` 형태소 분석 결과의 sparse TF vector
- Qdrant vector: `bm25`
- IDF: 현재 컬렉션의 Qdrant IDF modifier
- Dense embedding은 품질 실행에서 재사용할 수 있지만 해당 검색 점수에는 사용하지
  않는다.

### C. 기본 RRF

- Dense와 BM25가 각각 동일한 child candidate limit을 조회한다.
- Qdrant의 기본 RRF로 두 순위를 결합한다.
- 현재 `search_chunks` 운영 경로와 동일한 기준선이다.

### D1. Weighted RRF

- 개발셋에서 dense와 BM25의 상대 가중치를 coarse grid로 탐색한다.
- 최초 grid는 dense weight `0.25, 0.50, 0.75, 1.00`과 sparse weight
  `0.25, 0.50, 0.75, 1.00`의 조합으로 제한한다.
- 1차 선택 지표는 Recall@5, 동률이면 MRR@5, 다시 동률이면 기본 RRF와 가까운
  가중치를 선택한다.
- Qdrant client/server가 native weighted RRF를 지원하지 않으면 평가 전용 순위
  결합기를 사용한다. 이 경우 원본 dense/BM25 순위와 fusion 공식을 결과에 기록하고
  운영 경로에는 적용하지 않는다.

### D2. DBSF

- Dense와 BM25의 점수 분포를 정규화해 결합한다.
- 동일한 prefetch limit과 parent collapse 규칙을 사용한다.
- 현재 설치된 Qdrant client/server의 DBSF 지원 여부를 실행 시작 시 확인한다.
- 지원하지 않으면 자동으로 다른 알고리즘으로 대체하지 않고 해당 비교군을
  `unsupported`로 기록한다.

D1과 D2는 모두 실행하되 개발셋 결과가 더 좋은 하나만 held-out의 조정된 fusion
후보로 승격한다.

### E. 기본 RRF + 로컬 reranker

- 1차 후보 모델은 `BAAI/bge-reranker-v2-m3`로 고정한다.
- RRF가 넓게 수집한 child 후보만 reranking한다.
- 입력 pair는 `(retrieval_question, payload["text"])`이다. parent 전체 원문이나
  gold answer는 reranker 입력에 포함하지 않는다.
- 기본 candidate limit은 child 40개이며 개발셋에서 20과 40만 비교한다.
- child별 reranker 점수로 내림차순 정렬한 뒤 parent_id 기준 첫 등장 순서로
  중복을 제거하고 상위 parent top-k를 만든다.
- 모델 로딩 시간은 cold-start로 별도 기록한다. 품질 비교 latency에는 warm model의
  요청 시간만 포함한다.
- FP16 사용 여부, device, batch size, model revision, max sequence length를 run
  메타데이터에 기록한다.

Reranker는 후보에 없는 정답을 복구할 수 없다. 따라서 RRF child candidate
Recall@20/40을 함께 기록해 reranker의 이론적 상한을 확인한다.

## 공통 후보 및 Parent 정렬 규칙

현재 운영 경로의 `PARENT_EXPANSION_FETCH_MULTIPLIER = 4`를 기준으로 한다.

```text
requested parent top_k = 5
retrieval child limit  = 20
reranker child limit   = 20 or 40
```

Dense-only, BM25-only, RRF 및 조정 fusion은 모두 child 20개를 조회한다. 각 방식의
최종 parent 순위는 다음 규칙으로 만든다.

1. 검색 방식이 반환한 child 순서를 보존한다.
2. 유효한 `parent_id`가 없는 결과는 제외한다.
3. 동일 parent_id가 처음 나타난 위치를 parent 순위로 사용한다.
4. 중복 parent_id는 제외한다.
5. 상위 parent 5개가 채워지거나 child 후보를 소진하면 종료한다.

이 규칙을 공용 함수로 사용해 검색 방식별 parent 확장 차이가 결과에 섞이지 않게
한다. 공개 RAG 응답의 source ID도 기존과 같이 parent ID를 사용한다.

## 평가 지표

질문 `q`, 정답 parent 집합 `Gq`, 상위 k개 예측 parent 목록 `Pk`를 기준으로 한다.

### Recall@k

```text
Recall@k(q) = |Gq ∩ Pk| / |Gq|
```

여러 정답 조항이 필요한 질문에서는 일부만 검색한 경우 부분 점수를 준다. 전체
Recall@k는 질문별 Recall@k의 macro average다.

### Hit@k

```text
Hit@k(q) = 1 if Gq ∩ Pk is not empty, otherwise 0
```

Recall과 혼동하지 않도록 Hit@k도 결과 JSONL에 남긴다. 이력서에서는 어떤 정의를
사용했는지 반드시 명시한다.

### MRR@5

상위 5개 parent 중 첫 번째 정답의 rank를 `r`이라고 할 때 `1/r`을 사용한다.
정답이 없으면 0이다. 여러 정답 중 최초 정답만 MRR에 기여한다.

### nDCG@5

`gold_jo`에 포함된 parent를 relevance 1, 나머지를 0으로 두고 DCG@5를 이상적인
정렬의 IDCG@5로 나눈다. 여러 정답 조항의 상위 배치를 평가할 수 있다.

### 통계 비교

- 모든 차이는 같은 질문의 두 결과를 짝지은 paired difference로 계산한다.
- 개발셋과 held-out 각각 고정 seed로 10,000회 bootstrap해 평균 차이의 95%
  신뢰구간을 계산한다.
- 절대 개선은 `%p`, 상대 개선은 `%`로 별도 표시한다.

```text
절대 개선(%p) = After - Before
상대 개선(%)  = (After - Before) / Before * 100
```

분모가 0이면 상대 개선은 `N/A`로 기록한다.

## Latency 측정

품질 실행과 latency 실행을 분리한다.

### 품질 실행

- 질문당 dense/sparse representation은 한 번 만들고 모든 비교군에서 재사용한다.
- 검색 방식 차이만 비교하며 중복 embedding 호출로 인한 변동을 제거한다.
- 결과는 결정적이어야 하며 동일 run에서 방식별 parent 순위를 저장한다.

### Latency 실행

- 준비용 warm-up 질문은 집계에서 제외한다.
- 각 방식은 질문마다 3회 측정하고 실행 순서는 고정 seed로 교차시킨다.
- 다음 시간을 분리 기록한다.

```text
dense_embedding_ms
sparse_encoding_ms
qdrant_search_ms
fusion_ms              # client-side fusion일 때만
reranker_ms
retrieval_total_ms
```

- 평균, P50, P95를 보고한다.
- Reranker model load는 `reranker_cold_start_ms`로 분리한다.
- end-to-end 비교는 최종 후보에 대해서만 Qwen generation까지 포함해 별도 실행한다.

## 구성 요소

### 검색 전략 계층

Qdrant 호출 계층은 최소한 다음 전략을 표현해야 한다.

```text
dense
bm25
rrf
weighted_rrf
dbsf
```

기존 `search_chunks`는 기본 RRF 동작을 유지한다. 평가용 전략 선택이 기존 API의
암묵적 기본값을 바꾸지 않도록 새 명시적 인터페이스를 추가한다. 모든 전략은 공통
검색 결과 shape인 `id`, `score`, `payload`를 반환한다.

### 로컬 reranker adapter

Reranker는 검색 및 Qwen 클라이언트와 분리된 adapter로 둔다. 실험이 비활성화된
운영 경로에서는 모델을 import하거나 load하지 않는다. 대형 ML dependency는 기본
`requirements.txt`에 바로 추가하지 않고 별도 실험 dependency 또는 명시적 profile로
격리한다.

### Retrieval 평가 CLI

새 평가 CLI는 최소한 다음 입력을 받는다.

```text
--dataset
--split development|holdout
--methods
--top-k
--candidate-limit
--rerank-candidate-limit
--run-id
--output-dir
--seed
```

기본 출력 위치는 `reports/retrieval-eval/<run-id>/`이며 이 디렉터리는 Git ignore
대상이다. 출력 경로는 `reports/retrieval-eval` 하위만 허용한다.

### 실행 메타데이터

`run.json`은 다음을 포함한다.

```text
run_id
started_at
split
dataset_path
dataset_sha256
document_sha256
case_count
methods
top_k
candidate_limit
rerank_candidate_limit
embedding_model
reranker_model + revision
Qdrant client/server versions
fusion parameters
device + precision + batch size
seed
git_commit
```

환경 변수 값, 자격 증명, 원문 정책 내용은 기록하지 않는다.

## 결과 파일 계약

### `results.jsonl`

질문과 방법 조합당 한 레코드를 쓴다.

```json
{
  "case_id": "q01",
  "method": "rrf",
  "gold_parent_ids": ["jo-1"],
  "predicted_parent_ids": ["jo-1", "jo-99", "jo-3"],
  "predicted_child_ids": ["jo-1-hang-3", "jo-99-hang-1"],
  "recall_at_1": 1.0,
  "recall_at_3": 1.0,
  "recall_at_5": 1.0,
  "hit_at_5": true,
  "reciprocal_rank_at_5": 1.0,
  "ndcg_at_5": 1.0,
  "timing_ms": {
    "qdrant_search": 42,
    "reranker": 0
  }
}
```

질문 원문은 기본 결과에 쓰지 않고 `case_id`로 데이터셋을 참조한다.

### `summary.md`

최소한 다음 표를 생성한다.

| 방식 | Recall@1 | Recall@3 | Recall@5 | MRR@5 | nDCG@5 | 평균 검색 | P95 검색 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Dense-only | | | | | | | |
| BM25-only | | | | | | | |
| RRF | | | | | | | |
| Weighted RRF 또는 DBSF | | | | | | | |
| RRF + reranker | | | | | | | |

보고서는 각 비교의 paired difference와 95% 신뢰구간, RRF 대비 승/패/동률 질문 수,
candidate recall 상한 및 fallback 가능 질문 목록을 포함한다.

## 2단계 End-to-End 평가

검색-only 개발 결과에서 다음 세 방식만 Qwen 답변 생성 단계로 보낸다.

1. Dense-only Before
2. 현재 기본 RRF
3. 개발셋에서 선택된 최고 품질 후보

동일한 Qwen 모델, temperature, context budget 및 answer top-k를 사용한다. 기존
`scripts/export_rag_eval_answers.py`와 local Judge 평가 경로를 재사용하되 검색 방법을
명시적으로 주입한다. 다음 결과를 분리 보고한다.

- 핵심 답변 정답률
- 완전 정답률
- deterministic source Recall@5
- fallback 발생률과 fallback stage
- 출처 반환률
- 평균/P95 end-to-end latency

Qwen 생성 결과는 비결정적일 수 있으므로 검색-only 수치가 검색 알고리즘 선택의
1차 근거다. Judge 점수는 Judge metric으로 표시하고 사람 평가 정확도로 표현하지
않는다.

## 선택 및 배포 기준

### Fusion 후보 선택

- 개발셋 Recall@5가 가장 높은 방식을 선택한다.
- 동률이면 MRR@5, 다음으로 nDCG@5를 사용한다.
- 차이가 bootstrap 신뢰구간상 불명확하면 복잡성이 낮은 기본 RRF를 유지한다.

### Reranker 선택

- RRF candidate Recall@40이 충분한지 먼저 확인한다.
- RRF 대비 held-out Recall@5를 저하시키지 않으면서 MRR@5 또는 nDCG@5가 개선돼야
  한다.
- 품질 향상과 warm P95 latency 증가를 함께 보고하고, 단순 점수 상승만으로 운영
  기본값을 변경하지 않는다.

### 운영 적용

최종 held-out 결과가 확인된 후 별도 변경에서 선택된 방식만 제품 경로에 적용한다.
이 평가 작업 자체는 실험 harness와 보고서만 추가하며 기본 RRF 동작을 유지한다.

## 테스트 전략

새 동작은 테스트를 먼저 작성한다.

### 단위 테스트

- dense, BM25, RRF, DBSF query 구성이 올바른 named vector와 limit을 사용한다.
- 기본 `search_chunks`가 계속 RRF를 사용한다.
- parent collapse가 중복 parent를 첫 등장 순서로 제거한다.
- 여러 `gold_jo`를 가진 질문의 Recall@k, Hit@k, MRR@5, nDCG@5가 정확하다.
- weighted RRF의 고정 입력 순위가 결정적인 출력 순위를 만든다.
- bootstrap은 동일 seed에서 동일 신뢰구간을 반환한다.
- reranker가 child text만 입력받고 gold answer 또는 parent_text를 받지 않는다.
- unsupported DBSF가 silent fallback 없이 명시적으로 기록된다.

### CLI 및 산출물 테스트

- 개발/held-out split과 dataset hash가 `run.json`에 기록된다.
- 질문별 method 결과가 중단 직전까지 flush된다.
- 잘못된 run ID와 report root 밖 출력 경로를 거부한다.
- 부분 실패를 성공 평균에 포함하지 않고 method별 오류 수를 보고한다.
- raw question과 credentials가 run metadata에 기록되지 않는다.

### 실제 통합 검증

```powershell
docker compose up -d
docker compose run --rm rag-api pytest -v
curl http://localhost:6333
docker compose run --rm rag-api python -m app.healthcheck
```

그다음 개발셋 검색-only 실험, 선택된 방법의 end-to-end 실험, 마지막으로 고정
held-out 실험을 순서대로 실행한다. 실제 명령은 구현된 CLI `--help`와 함께 문서화한다.

## 구현 소유권과 순서

파일 소유권 충돌을 피하기 위해 다음 순서로 진행한다.

1. Qdrant 검색 전략과 query contract: `app/vector_store.py`,
   `tests/test_vector_store.py`
2. 검색 지표 및 CLI: 새 retrieval evaluation 모듈과 테스트
3. 로컬 reranker adapter와 격리된 dependency, 전용 테스트
4. 평가 산출물 writer와 summary 테스트
5. 최종 후보에 한한 `app/rag_pipeline.py` 의존성 주입 및 기존 회귀 테스트
6. 개발셋 실행 후 설정 고정
7. held-out 데이터셋 hash 고정 및 최종 1회 실행

서로 다른 subagent가 같은 소유 파일을 동시에 수정하지 않는다. RAG pipeline 적용은
retrieval 실험 결과가 확정된 이후 별도 단계로 수행한다.

## 완료 조건

- 동일 run에서 Dense-only, BM25-only, RRF, 조정 fusion, RRF+reranker를 비교한다.
- 모든 방식이 동일한 child candidate 및 parent collapse 계약을 사용한다.
- 개발셋과 held-out 데이터, 설정 및 결과가 명확하게 분리된다.
- Recall@1/3/5, Hit@k, MRR@5, nDCG@5와 latency 평균/P50/P95가 생성된다.
- paired improvement와 bootstrap 95% 신뢰구간이 보고된다.
- raw JSONL, run metadata 및 Markdown summary로 결과를 재현할 수 있다.
- 최종 이력서 문구는 held-out 결과만 사용한다.
- 기존 RRF 제품 경로, Qwen 전용 생성 규칙, 출처 반환 계약 및 로컬 배포 구조가
  유지된다.

## 이력서 결과 표현 계약

실제 held-out 결과가 나온 뒤에만 다음 템플릿의 변수를 채운다.

```text
50개 held-out 사내 정책 질문에서 Dense-only 대비 [선택 방식]으로
정답 조항 Recall@5를 X%에서 Y%로 Z%p 개선했다.
MRR@5는 A에서 B로 개선됐고, 검색 P95 latency 증가는 C ms였다.
```

`정확도 향상`이라는 포괄적 표현 대신 검색 지표의 이름과 평가 문항 수를 명시한다.
답변 정확도는 별도의 Qwen end-to-end 평가 결과가 있을 때만 추가한다.

## 관련 문서

- GitHub issue #1: <https://github.com/bbungjun/onpremis_rag_chatbot/issues/1>
- `docs/superpowers/specs/2026-08-05-natural-language-evaluation-set-design.md`
- `docs/superpowers/specs/2026-08-06-evidence-context-rag-design.md`
- `docs/superpowers/specs/2026-08-02-local-llm-judge-design.md`
- Qdrant Hybrid Queries: <https://qdrant.tech/documentation/search/hybrid-queries/>
- Qdrant Hybrid Search with Reranking:
  <https://qdrant.tech/documentation/advanced-tutorials/reranking-hybrid-search/>
- BGE-M3: <https://arxiv.org/abs/2402.03216>
- BGE reranker v2 M3: <https://huggingface.co/BAAI/bge-reranker-v2-m3>
