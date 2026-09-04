# RRF ablation 및 로컬 reranker 평가

## 한 줄 결론

50개 held-out 사내 정책 질문에서 Dense-only 대비 Dense+BM25 RRF가 정답 parent
조항 Recall@5를 0.96에서 1.00으로 4%p 높였다. 로컬 reranker는 검색 MRR@5를
0.8867에서 0.9800으로 높였지만 end-to-end 출처 Recall과 Judge 점수가 하락해 운영
기본값은 RRF로 유지했다.

## Before / 문제

기존 챗봇은 Qdrant에서 dense cosine 검색과 BM25 sparse 검색을 RRF로 결합했지만,
과거 76문항 전체 RAG 결과만 있었다. 이 결과로는 dense, BM25, RRF 중 어느 요소가
정답 조항 검색에 기여했는지 분리할 수 없었다. 동일 데이터로 질문 해석을 개발한
이력도 있어 기존 50문항을 최종 성과로 사용하면 데이터 누수 위험이 있었다.

또한 “RRF보다 reranker가 최신이므로 더 좋다”는 가설도 검색 순위만으로 판단할 수
없었다. reranker가 parent 조항의 순서를 바꾸면 context budget에 포함되는 출처가
달라지고, 최종 답변 품질이 오히려 낮아질 수 있기 때문이다.

## Why / 분석 및 평가 설계

- 기존 50문항은 development로만 사용하고 새로운 자연어 정책 질문 50개를
  `qa_holdout.jsonl`에 분리했다.
- 모든 방식에서 같은 `retrieval_question`, dense/sparse representation, Qdrant
  collection, child candidate 20개, parent-first collapse, parent top 5를 사용했다.
- Dense-only, BM25-only, RRF, 16개 Weighted RRF grid, DBSF를 비교했다.
- `BAAI/bge-reranker-v2-m3`는 RRF child 20/40만 재정렬했고 질문과 child text만
  입력했다. gold answer와 parent text는 입력하지 않았다.
- Recall@1/3/5, Hit@k, MRR@5, nDCG@5와 paired bootstrap 10,000회 95% CI를
  계산했다.
- retrieval과 Qwen end-to-end를 분리했다. 최종 E2E는 Dense, RRF,
  RRF+reranker만 같은 Qwen 설정으로 실행하고 Exaone local Judge로 평가했다.

## Solution / 구현

- 명시적 검색 전략: `dense`, `bm25`, `rrf`, `weighted_rrf`, `dbsf`
- first-ranked child 기준 공통 parent collapse
- 결정적 ranking metric 및 seed 고정 paired bootstrap
- 실행 중 질문별 `results.jsonl` 즉시 flush, `run.json`, `summary.md` 생성
- optional `requirements-reranker.txt`와 lazy Transformers adapter
- 기존 `answer_question`의 기본 RRF를 보존하는 검색 dependency injection
- 내보낸 답변을 재생하는 local Judge 경로와 Exaone JSON fence/개행 정규화
- 50개 held-out 문항의 중복, 조항 번호 노출, gold parent 존재 여부 자동 검증

원시 질문·검색 결과·생성 답변이 포함된 실행 디렉터리는 Git에서 제외했다.

## Development 결과 / 설정 선택

Development 50문항에서 Dense Recall@5는 0.96, RRF는 0.98, DBSF는 1.00이었다.
Weighted RRF 16개 조합의 최고 Recall@5는 0.98이어서 조정 fusion 후보는 DBSF로
고정했다.

RRF+reranker는 candidate 20과 40 모두 Recall@5 1.00, MRR@5 0.96으로 같았다.
평균 검색+rereank 지연은 candidate 20이 158.29ms, candidate 40이 283.00ms여서
candidate 20을 최종 설정으로 고정했다. 이 선택 이후 held-out 설정은 변경하지 않았다.

## After / held-out 검색 결과

환경: RTX 3070 Ti 8GB, reranker CUDA FP16, batch 8, max length 512, Qdrant
server 1.18.2, child candidate 20, parent top 5, latency 3회 반복.

| 방식 | Recall@1 | Recall@3 | Recall@5 | MRR@5 | nDCG@5 | 평균 검색 | P50 | P95 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Dense | 0.84 | 0.94 | 0.96 | 0.8917 | 0.9091 | 8.86ms | 7.88ms | 16.19ms |
| BM25 | 0.50 | 0.84 | 0.92 | 0.6747 | 0.7367 | 9.09ms | 7.88ms | 16.55ms |
| RRF | 0.80 | 0.96 | 1.00 | 0.8867 | 0.9156 | 9.53ms | 9.64ms | 14.16ms |
| DBSF | 0.80 | 1.00 | 1.00 | 0.8933 | 0.9209 | 9.33ms | 8.98ms | 14.80ms |
| RRF + reranker | 0.96 | 1.00 | 1.00 | 0.9800 | 0.9852 | 154.81ms | 154.41ms | 176.91ms |

Dense 대비 RRF, DBSF, reranker의 Recall@5 paired 차이는 모두 +0.04였고 10,000회
bootstrap 95% CI는 `[0.00, 0.10]`이었다. 50문항에서 개선된 질문은 2건이므로
효과를 통계적으로 확정적이라고 표현하지 않는다. RRF와 DBSF의 Recall@5가 같고
DBSF의 추가 이득도 작아 단순한 기존 RRF를 유지했다.

reranker는 Recall@5가 아니라 상위 배치를 개선했다. RRF 대비 Recall@1은
0.80→0.96, MRR@5는 0.8867→0.9800이었지만 검색 P95가 14.16ms→176.91ms로
162.75ms 증가했다.

## End-to-end 결과

모든 값은 사람 평가 정확도가 아니라 deterministic source metric과 Exaone local
Judge metric이다.

| 방식 | fallback | 출처 반환 | source Recall | 평균 E2E | P95 E2E | Judge correctness | Judge total |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Dense | 4/50 | 47/50 | 0.88 | 11.60s | 26.24s | 1.68/2 | 4.56/6 |
| RRF | 1/50 | 49/50 | 0.96 | 11.76s | 21.25s | 1.78/2 | 4.72/6 |
| RRF + reranker | 4/50 | 46/50 | 0.92 | 17.43s | 30.75s | 1.62/2 | 4.40/6 |

reranker는 검색-only 순위를 개선했지만, 긴 parent 조항이 context budget에서 제외되는
순서도 바꾸어 최종 출처 Recall과 답변 Judge 점수를 낮췄다. 따라서 운영 적용 기준을
충족하지 못했고 기본 RRF를 유지했다.

## 검증 및 증거

주요 재현 명령:

```powershell
docker compose up -d
docker compose run --rm -T rag-api pytest -q
docker compose run --rm -T rag-api python scripts/evaluate_retrieval.py --help
curl http://localhost:6333
docker compose run --rm -T rag-api python -m app.healthcheck
```

채택한 실행 증거:

- 변경 범위 회귀 테스트: `72 passed`
- 저장소 테스트(기존 agent setup 계약 테스트 제외): `258 passed, 1 skipped`
- 전체 테스트: `267 passed, 1 skipped, 2 failed`. 두 실패는 이번 변경과 무관하게
  `.env.shared-ec2.example`의 placeholder URL과
  `tests/test_agent_setup_contract.py`가 기대하는 고정 EC2 URL이 달라 발생했다.
- 정적 검사: `uvx ruff check app scripts tests` 통과
- 최종 CLI smoke run: `reports/retrieval-eval/final-audit-rrf-20260831/`
- retrieval development: `reports/retrieval-eval/dev-fusion-050-20260831-r2/`
- reranker development: `dev-reranker-c20-20260831`, `dev-reranker-c40-20260831`
- retrieval held-out: `reports/retrieval-eval/holdout-final-20260831/`
- Qwen E2E: `e2e-holdout-dense-20260831`, `e2e-holdout-rrf-20260831`,
  `e2e-holdout-reranker-20260831-r3`
- local Judge: `judge-holdout-dense-20260831-r3`,
  `judge-holdout-rrf-20260831-r3`, `judge-holdout-reranker-20260831-r4`
- held-out SHA-256:
  `23750507b67c1ca0727e578bca9dfbd9c19a05d59c1fcfee574f5d4c2cf9a11c`
- document SHA-256:
  `4ecef7ee4a5a8b3eb1c6c1e23ad387618b85c2b382e3c97894a365932e9356cc`

## 실패와 제한사항

- 첫 Docker 실행은 이미지 안에 Git CLI가 없어 commit hash 수집 단계에서 실패했다.
  이후 metadata는 `unavailable`을 허용하도록 수정했다.
- 최초 reranker E2E 실행은 host 환경의 기본 모델명이 실제 Ollama tag와 달라 50건이
  실패했고, 다음 실행은 CPU 기본값으로 실행되어 최종 결과에서 제외했다. 채택 결과는
  검색-only와 같은 CUDA FP16 설정의 `r3`이다.
- Exaone은 JSON을 Markdown fence로 감싸거나 rationale 안에 비표준 개행을 출력했다.
  fence/개행을 정규화하고 1회 재시도하며, 최종 채택 Judge 실행은 모두 50/50 성공했다.
- held-out은 50문항이라 질문 1건이 2%p이다. CI 하한이 0이므로 +4%p를 일반화된
  통계적 우월성으로 표현하지 않는다.
- 데이터셋은 실제 기밀 사내 문서가 아니라 프로젝트의 합성 규정집이다.
- Judge 결과는 사람 평가가 아니며 답변 정확도로 단정하지 않는다.

## 이력서용 문구

> 50개 held-out 사내 정책 질문에서 Dense-only 대비 Dense+BM25 RRF로 정답 조항
> Recall@5를 96%에서 100%로 4%p 개선했습니다. 로컬 bge reranker는 MRR@5를
> 0.8867에서 0.9800으로 높였지만 검색 P95가 162.75ms 증가하고 end-to-end 출처
> Recall이 하락해, 품질·지연·답변 영향까지 검증한 뒤 기본 RRF를 유지했습니다.
