# A/B 직접 재검토와 승격 게이트: A 승격 보류

## Before / 문제

이전 오프라인 실험에서 EXAONE은 기존 50문항에 A 5.82, B 5.56점을 부여했지만, 답변에 없는
내용을 있다고 채점하는 오류가 확인됐다. 평균만 보면 A가 좋아 보였으나 이 점수로 운영 기본값을
변경할 근거는 부족했다. 또한 기존 98문항에는 상대 기간 조건 추출이나 검색 재작성 발동이 0건이었다.

사용자는 현재 세션에서 A/B를 재검토하고 비교 결과에 따른 승격을 요청했다. A는 원문을
canonical_question으로 쓰는 후보, B는 현재 예측 intent 지시문이다. 여기서 승격 범위는
canonical 지시문만이며, 질문 정규화·검색 재작성·system prompt·출처 처리는 유지한다.

## Why / 판정 방식

EXAONE의 평균 점수를 다시 정답으로 삼지 않고, 저장된 문맥/답변에서 사실·근거·필수 정보·출처를
대조했다. 검토자는 현재 대화 세션의 AI이며 이전 결과와 A/B 조건을 알고 있다. 모델 backend ID는
검증하지 못했으므로 GPT-6 Astra의 독립 블라인드 벤치마크로 표기하지 않는다. 사람 검수도 아니다.

단순히 상대적으로 덜 나쁜 답변을 승자로 만들지 않도록 pass/fail과 critical 오류를 분리했다.
두 답변 모두 모순되면 both_fail이다. 필요한 정보를 빠뜨린 답변도 pass하지 않지만, 이 누락과
근거 없는 허용/불허 판정 등의 critical 오류는 따로 기록한다. 날짜 판단 결론이 맞아도 설명에서
달력일을 영업일로 단정하거나 날짜 관계를 잘못 계산하면 온전한 pass가 아니다.

### 사전 고정한 승격 조건

1. B에는 없는 critical 오류가 A에 새로 나타나는 사례가 없어야 한다.
2. 입력이 실제로 다른 반복 실험에서 A가 나빠진 결과가 없고 적어도 한 문항이 개선돼야 한다.
3. 최종 기본값 변경에는 대표성 있는 독립 확인 세트와 검증된 채점 기준이 필요하다.

이번 진단 표본 및 단일 연차 시나리오군의 stress test는 3번을 충족하지 않는다. 그와 별개로
실제 결과가 1번과 2번에도 미달하므로, 단순히 사람 승인만 기다리는 상태가 아니라 후보 자체에
확인된 문제가 있는 상태다. 승격 게이트는 판단을 JSON으로 기록하며 운영 설정을 자동 변경하지 않는다.

## Solution / 수행한 작업

- 점수가 갈린 9문항 전체(q11/q26/q29/q32/q43/q45/r14/r46/r48)를 문맥과 직접 대조했다.
- 동점 대조 q01과 q41을 추가 확인했다. 두 대조는 선택 표본이며 무작위 표본이 아니다.
- 생성 전에 상대 기간 4문항과 기대 조건을 `datasets/eval/intent_ab_boundary.jsonl`에 고정했다.
- `scripts/review_intent_ab.py`로 prepare/generate/gate 단계를 실행했다. 기존 B의 검색 질문으로
  한 번 검색하고 같은 parent 문맥을 A/B에 제공했다. 3개 seed를 공유한 3회 반복, 24답변이다.
- AI 검토 레코드에 pass, critical, 근거, 판정 이유와 입력 동일 여부를 남겼다. 원문 파일 해시를
  검증하고 누락/중복 검토나 같은 입력에서 생긴 승리를 승격 근거로 인정하지 않도록 했다.

생산 `question_interpreter.py`, `rag_pipeline.py`, system prompt와 기본값은 변경하지 않았다.

## Verification

실행일 2026-09-09 KST. 생성 모델 qwen3:4b-instruct, think=off, temperature=0.2,
num_ctx=4096, num_predict=2048, bge-m3, Qdrant RRF top-k 5/후보 20개.
Ollama 0.32.5, Qdrant 1.18.2, RTX 3070 Ti 8GB의 기존 로컬 Docker/호스트 Ollama 환경이다.
생성/검토가 끝난 후 Ollama의 적재 모델 목록이 비어 있음을 확인했다.

```powershell
docker compose up -d
docker compose run --rm rag-api python scripts/review_intent_ab.py prepare --run boundary-20260909
docker compose run --rm rag-api python scripts/review_intent_ab.py generate --run boundary-20260909
# 현재 세션이 작성한 검토 레코드와 artifact 해시를 같은 run 폴더에 기록한 후:
docker compose run --rm rag-api python scripts/review_intent_ab.py gate --run boundary-20260909
docker compose run --rm rag-api pytest -v
curl.exe -fsS http://localhost:6333
docker compose run --rm rag-api python -m app.healthcheck
uvx ruff check .
uvx ruff format --check .
```

- TDD: 구현 전 `scripts.review_intent_ab`가 없어 수집 실패. 구현 후 새 테스트 5건 통과.
- 전체 pytest: **338 passed, 2 skipped (8.54s)**. Git CLI 의존 검사와 opt-in EXAONE live 검사 스킵.
- Qdrant 응답, 앱 설정 healthcheck, Ruff lint/format 통과.
- 실제 Qwen: **24/24 answered**, generation_error 0, length 중단 0.
- 자동 테스트는 게이트/실행기 계약 검증이며 AI의 의미 판단 정확도 검증은 아니다.

## After / 재검토 결과

### 기존 9개 차이 문항

| 문항 | 판정 | 근거 |
| --- | --- | --- |
| q11 | B 우세 | A는 검색 문맥에 기준이 없는데 미충족 단정. B는 확인 불가로 제한 |
| q26 | 둘 다 실패 | 두 답변 모두 사용자 조건 없는 미충족 단정. B는 명시된 기준까지 부정 |
| q29 | A 우세 | B에 잘못된 근거 조 번호 |
| q32 | A 우세 | B가 명시된 일반 사원의 반납·폐기 절차를 없다고 주장 |
| q43 | 둘 다 실패 | 재택근무에도 적용되는 상위 승인 조건을 부정 |
| q45 | A 우세 | B가 기한을 답하고도 근거 없는 미충족 결론 추가 |
| r14 | 둘 다 실패 | 오타를 별도 개념으로 취급해 부당한 거절 |
| r46 | 둘 다 실패 | 조건 미상을 미충족으로 단정; 기존 B 만점은 부적절 |
| r48 | 둘 다 실패 | 모호한 구매 의사를 절차 미충족으로 단정; 기존 A 만점은 부적절 |

9건 결과는 A 우세 3 / B 우세 1 / 둘 다 실패 5다. A의 우세 3건만으로 승격하지 않는다.
점수 차이가 있는 문항만 선택한 진단 결과라 전체 품질 개선률이 아니다.

동점 대조: q01은 둘 다 통과. q41은 둘 다 질문의 교육 시간 정보를 누락해 실패다. 기존
EXAONE이 두 답변 모두 만점을 줬으므로, 점수가 같은 문항도 무조건 정답으로 취급하면 안 된다.

### 보완 상대 기간 실험

각 문항 A/B를 서로 다른 seed 3개로 실행했다. 아래 통과는 결론과 설명이 모두 기준에 맞는 경우다.

| 문항 | 기대 판단 | A 통과 | B 통과 |
| --- | --- | ---: | ---: |
| ab01: 내일 사용 | 최소 사전 기한 부족 | 3/3 | 3/3 |
| ab02: 이틀 뒤 사용 | 최소 사전 기한 부족, 달력일 임의 환산 금지 | 0/3 | 3/3 |
| ab03: 정확히 3영업일 뒤 사용 | 최소 기한 충족 | 0/3 | 0/3 |
| ab04: 4일 뒤, 주말/공휴일 미상 | 영업일 확인 전 단정 불가 | 0/3 | 1/3 |
| 합계(진단 표본) | | 3/12 | 7/12 |

ab02의 A는 세 번 모두 **미충족이라는 최종 결론 자체는 맞았다.** 그러나 설명에서 달력일 이틀을
2영업일로 단정하거나 현재와 사용일의 기준을 혼동하거나 달력 없이 마감 시점을 계산했다.
이 설명 오류는 critical과 별도로 분류했지만 pass는 부여하지 않았다.

ab03은 A/B 모두 사용일까지 남은 기간을 신청일이 사용일보다 뒤인 것으로 오해하거나, 정확히
최소 기한을 맞춘 상황을 미충족으로 판정했다. 실제 B 분류는 deadline_lookup, 추출 conditions는
빈 dict였다. `3영업일` 표현이 lead_time으로 추출되지 않은 사실은 확인했지만 그것만을 전체
오답의 원인으로 단정하지 않는다.

ab04는 A가 세 번 모두 근거 없는 미충족 판정을 냈다. B는 한 번은 판단 불가로 답했지만,
나머지는 각각 미충족/무조건 충족으로 잘못 단정했다. B도 안정적이지 않다.

24개 생성이 모두 성공한 것과 24개 답변이 정확한 것은 다른 결과다. 이 4문항은 모두 연차
시나리오군에 속하므로 12회 반복을 독립된 12개 사용자 질문으로 해석하지 않는다.

## 승격 판정

**hold — A 기본값 승격 보류, 기존 B 기본값 유지.**

- 새 critical regression: 기존 q11과 보완 ab04/repeat=0. B는 critical이 없고 A에만 있다.
- 보완 12쌍: A 승 0 / B 승 4 / 둘 다 통과 3 / 둘 다 실패 5.
- 전체 검토 레코드는 12/12쌍 존재하며 누락/예상 밖 ID는 0.
- 별도의 대표성 있는 독립 확인 평가도 아직 없다.

이것은 B의 품질을 인증하거나 B를 새로 승격한 결과가 아니다. 현재 A로 교체할 근거가 미달해
기존 상태를 유지하는 결정이다. 다음 후보는 정보 부족과 미충족을 구분하고 상대 기간 해석을
바로잡는 변경으로 별도 검증해야 한다. 이번 작업에서 그런 운영 수정을 묶어 넣지 않았다.

## Evidence and Limitations

- [설계 및 사전 기준](../superpowers/specs/2026-09-09-intent-ab-promotion-design.md)
- [기존 A/B/C 실험](2026-09-08-intent-ablation.md)
- [검토용 PR #12](https://github.com/bbungjun/onpremis_rag_chatbot/pull/12)
- 기반 커밋 `22c4f78`. 기존 평가 아티팩트는 덮어쓰지 않았다.
- 원시 기록: `reports/local-judge/intent-ab-promotion/boundary-20260909/` (Git ignored).
- 세션 AI는 비블라인드이며 Judge 자체의 calibration이나 사람 일치율을 검증한 것은 아니다.
- 4문항 x 3회는 실패 재현용 stress test다. 유의성/모집단 비열등성/실사용 트래픽 A/B 검증이 아니다.

SHA-256:

```text
boundary dataset: 27f54ed5b42dad9dbe71688ad9a4d63784173657ac67feee2734aee44feb3959
contexts.jsonl:   efd2683244c3b8de05325b8c766217f2f103c24d027df804208738d86ad93739
answers.jsonl:    a42210a82b97fb1600ae994d1a8cc7a382f1ef882a063608c1c58305641a85cf
```

review-metadata.json에는 이전 답변/문맥과 새 답변/문맥, 두 검토 파일의 해시를 모두 기록했다.
promotion.json에 게이트 실패 사유와 구체적인 regression ID가 저장돼 있다.
