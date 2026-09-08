# 고정 문맥에서 no / predicted / gold intent 답변 비교

## Before / 문제

현재 intent 일치율 39/98(39.8%)는 AI가 작성한 잠정 라벨에 대한 분류 지표다. 이 값만으로
사내 규정 답변이 나쁘거나 intent를 개선해야 한다고 판단할 수 없었다. 실제로 GENERAL_QA도
검색과 Qwen 생성은 수행한다. 기존 구현에는 intent에 따른 검색 문장 재작성과 질문 길이에
따른 parent 축소가 있어 단순 on/off 비교에는 검색 문맥 차이까지 섞인다.

## Why / 통제 조건

이번 실험은 같은 검색 문맥에서 canonical 지시문만 바꾸는 평가다.

| 조건 | canonical_question |
| --- | --- |
| A / no_intent | 사용자 원문 |
| B / predicted_intent | 현재 분류기가 선택한 기존 지시문 |
| C / gold_intent | 잠정 gold 라벨로 선택한 기존 지시문 |

세 조건 모두 기존 system prompt와 injection guard를 사용한다. no-intent도 이 공통 system
prompt를 받으며, 모든 질문 해석을 제거한 제품과 같지는 않다. C는 정답 답변/조항을 Qwen에
전달하지 않고, 추출 조건도 B와 같다. gold가 넓게 정의한 날짜/주기와 기존 deadline 템플릿의
범위 차이가 있어 C도 완벽한 의도 이해의 상한은 아니다.

정규화된 원문으로 RRF 검색을 문항당 한 번만 수행했다. 후보 20개에서 parent top-k 5를
선택한 뒤 세 프롬프트 중 가장 긴 것을 기준으로 함께 줄였다. 동일 조문 내용·순서와 source
ID가 유지되며 단일 parent가 예산을 넘으면 중단한다. 98건 모두 검색 문맥이 확보됐다.
기존 50문항의 고정 문맥 source Recall은 0.96이며, 조건 간 차이가 날 수 없는 통제값이다.
고정 문맥에 나타난 고유 parent 82개의 본문을 현재 regulations.md를 청킹한 결과와 비교했고,
82개 모두 정확히 일치했다. 컬렉션의 실제 문맥과 로컬 원문 간 차이는 발견되지 않았다.

98건 중 A/B 입력이 완전히 같은 문항은 68건, B/C 입력이 같은 문항은 39건이다. 동일 입력에서도
추론 실행 변동이 생길 수 있으므로 이런 문항의 답변 차이는 intent 효과로 해석하지 않는다.

## Solution / 구현

- `app/intent_ablation.py`: 공통 문맥, arm 구성, 순차 생성, 별도 Judge와 paired 집계.
- `scripts/compare_intent.py`: prepare/generate/judge/summary 단계와 해시 검사.
- JSONL 레코드를 매 응답마다 flush/fsync해 중단 전에 끝난 결과를 보존한다. 재실행은 기존
  성공/실패 레코드를 모두 보존하고 남은 것만 처리한다. 실패를 지우고 재시도하지 않는다.
- 원문, 검색 문맥, 정확한 프롬프트, 원시 Ollama 응답, 채점 시도, 오류, 모델 digest와 설정을
  `reports/local-judge/intent-ablation/intent-abc-20260908/`에 저장한다(Git ignore 확인).
- 답변을 생성하는 Qwen과 평가하는 EXAONE을 순차로 실행하고 각 단계 종료 후 모델을 내린다.
  실제 서비스의 질문 해석·검색·생성 코드는 수정하지 않았다.

## Verification / 실행 조건

실행일 2026-09-08 KST. 기준 커밋 `813c48d` (생산 코드 `d8ec28a` + intent 평가).

| 항목 | 설정 |
| --- | --- |
| GPU | RTX 3070 Ti 8GB, NVIDIA 591.86 |
| 시스템 RAM | 31.84 GiB, 준비 시 여유 5.67 GiB |
| Ollama / Qdrant | 0.32.5 / 1.18.2 |
| 임베딩 | bge-m3 |
| Qwen | qwen3:4b-instruct, think=off, temperature=0.2 |
| 생성 예산 | num_ctx=4096, num_predict=2048 |
| Judge | exaone3.5:7.8b, temperature=0, num_ctx=4096, num_predict=768 |
| 실행 | 문항별 A/B/C 순서 6가지 순환, 문항별 동일 seed, 조건당 1회 |
| 주 평가 | qa_set 50건, 기존 reference 답변 제공(Judge에만) |
| 탐색 평가 | robustness 48건, reference 없이 고정 문맥에 대해 Judge 평가 |

데이터 SHA-256:

```text
qa_set:     1c9fb38eda3ce4ff01537792dbbf39178b93388fe4d5ef69257488ab587b7ae8
robustness: 6d7fb082a9ac5aed847c0bf0bbdaad0b3de57c26088bc69278862b27cb490623
intent_gold:8b4ae5b062eab8f9b42a5c96b6080da6ec77f0fdd3eded017581f012d93269ed
regulations:24e5ccdfd77863dc94c6d3af20ce0c25f6d8d49e2b4da3277089fa8558e060d2
```

재현 명령(새 실행은 다른 run 이름 필요):

```powershell
docker compose up -d
docker compose run --rm rag-api python scripts/compare_intent.py prepare --run intent-abc-20260908
docker compose run --rm rag-api python scripts/compare_intent.py generate --run intent-abc-20260908 --ids q01,q03,q20,q30,q22,r37
docker compose run --rm rag-api python scripts/compare_intent.py generate --run intent-abc-20260908
docker compose run --rm rag-api python scripts/compare_intent.py judge --run intent-abc-20260908
docker compose run --rm rag-api python scripts/compare_intent.py summary --run intent-abc-20260908
```

6문항 18답변의 예비 실행 후 동일 설정으로 나머지를 이어서 실행한다. 예비 실행 결과를 보고
gold, 문맥, 프롬프트, 모델 설정을 변경하지 않았다. 예비 실행과 본 실행 각각 첫 모델 로딩이
포함되어 지연 비교에는 cold load 차이가 존재한다.

검증:

```text
TDD: 새 모듈 없음으로 수집 실패 -> 구현 후 새 테스트 14 passed
docker compose run --rm rag-api pytest -v -> 331 passed, 2 skipped (7.28s)
uvx ruff check . -> pass
uvx ruff format --check . -> pass (기존 eval_intent 출력문 포맷 1곳 정리)
curl.exe -fsS http://localhost:6333 -> Qdrant 응답
docker compose run --rm rag-api python -m app.healthcheck -> 설정 출력 성공
```

스킵은 Git CLI 의존 검사와 명시적 실행 플래그가 필요한 EXAONE live test다. Judge 모델을
직접 호출하는 실험은 이 live pytest와 별도로 기록한다.

## After / 결과

Qwen 294/294 답변 생성 완료. 빈 답변, 요청 오류, length 중단 모두 0건.
최초 EXAONE 채점은 6건 모두 JSON 검증에 실패해 중단했다. 대문자 점수 키와 JSON 밖 rationale을
반환했기 때문이다. 실패 원문 12회는 judgments.jsonl에 보존했다. 중단 시 다음 요청 1건은
완료 레코드가 없으며 성공으로 세지 않는다. JSON schema를 적용한 별도 채점 실행으로 이어간다.
최종 Judge 비교 결과는 측정 완료 후 갱신한다.

## Evidence and Limitations

1. AI 단독 intent 라벨과 EXAONE Judge 평가다. 독립적인 사람 평가가 아니다.
2. 개발 데이터 단일 실행이다. 유의성, 일반화, 실제 사용자 트래픽 분포를 주장하지 않는다.
3. robustness에는 옛 base_id와 모호한 문항이 있다. 정답을 상속하지 않고 50문항 주 평가와
   따로 보고한다. 같은 원문의 변형은 독립 표본이 아니다.
4. 점수 차이는 완전한 A/B/C 채점 묶음에서만 계산하고 누락 수를 같이 표기한다.
5. 모델 설정 seed는 실행의 완전한 결정성을 보장하지 않는다. 입력이 같은 조건의 차이도
   확인해야 하며 소수 문항의 차이로 intent 효과를 단정하지 않는다.
6. 다른 데스크톱 앱이 GPU/RAM을 사용 중이다. 메모리는 관측 시점 값이며 peak 측정이 아니다.
   생성 latency는 모델 로딩·캐시·프롬프트 길이 영향이 포함되고 실제 RAG 전체 latency가 아니다.
   예비 실행과 본 실행 사이에는 모델을 내렸다가 다시 올렸으며, 예비 18답변은 다시 생성하지
   않고 checkpoint에서 이어서 사용한다. 메모리 스냅샷은 runtime.jsonl과 도구 실행 기록에 있다.
7. 출처 regex와 거절 문구 검사는 휴리스틱이다. 거절 표현 검출을 오거절률로 부르지 않는다.
8. 기존 주입 공격 세트는 이번 실험 범위에 없으며 안전성 개선을 주장하지 않는다.
