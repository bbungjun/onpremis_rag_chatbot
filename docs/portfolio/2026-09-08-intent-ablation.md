# 고정 문맥에서 no / predicted / gold intent 답변 비교

동일 검색 문맥으로 Qwen 294답변을 생성하고 EXAONE schema-v2로 294건 전부 채점했다.
주 평가 50문항의 A/B/C 평균은 5.82/5.56/5.70점(6점 만점). 이번 단일 실행에서 intent
지시문의 이득은 입증되지 않았다. 생성 변동과 Judge 오독을 확인했으므로 기능 제거/강화의
확정 근거로 사용하지 않는다.

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
docker compose run --rm rag-api python scripts/compare_intent.py judge --run intent-abc-20260908 --judge-run schema-v2
docker compose run --rm rag-api python scripts/compare_intent.py summary --run intent-abc-20260908 --judge-run schema-v2
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

Judge 출력 형식 수정 후 전체 테스트는 333 passed, 2 skipped (6.98s)다. 추가 테스트는
Qwen에는 JSON schema가 적용되지 않는 것과, 재채점에서 전송 코드만 바뀌는 것은 허용하되
데이터/분류기/문맥 구성 코드가 바뀌면 거부하는 것을 검증한다.

## After / 결과

Qwen 294/294 답변 생성 완료. 빈 답변, 요청 오류, length 중단 모두 0건.
최초 EXAONE 채점은 6건 모두 JSON 검증에 실패해 중단했다. 대문자 점수 키와 JSON 밖 rationale을
반환했기 때문이다. 실패 원문 12회는 judgments.jsonl에 보존했다. 중단 시 다음 요청 1건은
완료 레코드가 없으며 성공으로 세지 않는다. JSON schema를 적용한 별도 채점 실행을 완료했다.
주 평가 50문항은 schema-v2에서 완전한 50개 triplet이 확보됐다. 각 평균은 동일 50문항의
정확성+근거성+완전성(각 0..2) 합산 Judge 점수다. 사람 평가 정확도가 아니다.

| 주 평가 50문항 | A | B | C |
| --- | ---: | ---: | ---: |
| 평균 Judge total / 6 | 5.82 | 5.56 | 5.70 |

| 비교 | 평균 점수 차이 | 승 / 무 / 패 |
| --- | ---: | ---: |
| B - A | -0.26 | 1 / 44 / 5 |
| C - A | -0.12 | 1 / 45 / 4 |
| C - B | +0.14 | 5 / 42 / 3 |

단일 실행에서 특화 지시문을 넣은 조건의 평균이 A보다 높지 않았다. 아래의 생성 변동과
Judge 오류 때문에 동등성이나 A의 우월성, intent 제거의 안전성을 확정하지 않는다.

점수가 갈린 주 평가 문항 전체:

| ID | A / B / C | 해석상 주의 |
| --- | --- | --- |
| q11 | 0 / 3 / 3 | 필요한 기준 조항이 검색 문맥에서 누락; B/C 동일 입력 |
| q26 | 6 / 4 / 6 | A/B 동일 입력인데 생성 내용 차이; intent 효과로 귀속 불가 |
| q29 | 6 / 4 / 6 | B에서 잘못된 조 번호 등장 |
| q32 | 6 / 3 / 6 | B/C 동일 입력인데 점수 차이 |
| q36 | 6 / 6 / 4 | C가 질문에 없는 대상 조건을 언급하고 불필요한 부정 결론 추가 |
| q41 | 6 / 6 / 3 | A/B의 누락을 Judge가 놓침; C도 불필요한 거절 |
| q43 | 3 / 0 / 3 | B/C 동일 입력인데 점수 차이 |
| q45 | 6 / 0 / 4 | B/C 답변은 매우 유사한데 Judge 점수가 크게 차이남 |
| q46 | 6 / 6 / 4 | B/C 동일 입력인데 점수 차이 |

원시 답변과 채점 이유를 대조한 에이전트 점검에서 Judge 한계도 확인했다.
q41 A/B 답변에는 필요한 교육 시간 정보가 없는데 Judge는 시간까지 포함했다고 설명하며
완전성 2점을 부여했다. q45 B에는 제출 기한이 명시돼 있는데 Judge는 기한을 제공하지 않았다고
설명했다. q20 A에서도 후보에 없는 예외 설명이 포함됐다고 주장했다. 이 점검 역시 사람 평가가
아니며, 결과는 수정하지 않고 그대로 보존했다. 현재 Judge로 작은 점수 차이를 신뢰하기 어렵다.

탐색 평가 48문항도 완전한 48개 triplet을 확보했다. reference가 없는 평가여서 위 주 평가와
합쳐 하나의 품질 점수로 보고하지 않는다.

| 탐색 유형 | 문항 수 | A | B | C |
| --- | ---: | ---: | ---: | ---: |
| 붙여쓰기 | 12 | 6.000 | 6.000 | 5.750 |
| 오타 | 12 | 5.750 | 5.833 | 5.583 |
| 구어체 | 12 | 5.750 | 5.750 | 5.833 |
| 애매 | 12 | 4.250 | 4.250 | 4.250 |
| 탐색 전체 | 48 | 5.438 | 5.458 | 5.354 |

탐색 전체 B-A는 +0.0208점(승/무/패 2/45/1), C-A는 -0.0833점(3/42/3), C-B는
-0.1042점(1/45/2)이다. raw summary에는 반올림 전 값이 있다.

주 평가에서 C-B +0.14점을 분류 개선으로 해석하면 특히 위험하다. B/C 입력이 같은 21문항에서
점수 합 차이가 +8점이고, 라벨을 바꿔 입력이 달라진 29문항에서는 -1점(평균 -0.0345점,
승/무/패 2/25/2)이었다. 즉 전체 +7점의 차이는 라벨 교체 효과를 뒷받침하지 않는다.
탐색에서는 B/C 동일 입력 18문항의 점수 합 차이 0점, 변경된 30문항은 -5점이었다.

최종 schema-v2: 294/294 judged, 294회 요청, 재시도 0, judge_error 0. 초기 plain JSON의
6개 실패는 별도 이력으로 유지했다. Judge 최대 입력 2,598 tokens, 최대 출력 179 tokens였다.
Qwen 요청 시간 합은 760.106초, schema-v2 Judge 요청 시간 합은 598.397초다. 이 합에는
개발/도구 대기, 검색, 초기 실패한 Judge 단계 시간이 포함되지 않으므로 전체 작업시간이 아니다.

한 조건이라도 6점 미만인 문항 전체는 q11/q26/q29/q32/q36/q41/q43/q45/q46,
r09/r14/r23/r26/r37/r38/r42/r44/r45/r46/r48이다. 성공 사례만 남기지 않았다.

출력 schema는 Ollama의 `format`에 correctness/groundedness/completeness(0,1,2)와
rationale을 명시하는 방식으로 강제했다. 점수 기준과 후보 답변은 변경하지 않았다.
[Ollama Structured Outputs](https://docs.ollama.com/capabilities/structured-outputs)
문서의 JSON Schema 방식을 적용했다. 1차 생성 코드 전체는 커밋 `4579c92`에 남아 있다.
새 judge_config-schema-v2.json은 전송 코드 해시, 답변 파일 해시와 설정을 기록한다.
1차 judgments.jsonl과 schema-v2 결과는 합산하지 않는다.

생성 관측값(98문항/조건, 모델 로딩 포함; latency 개선 실험으로 해석하지 않음):

| 항목 | A | B | C |
| --- | ---: | ---: | ---: |
| 요청 성공 | 98 | 98 | 98 |
| 평균 요청 시간(s) | 2.556 | 2.487 | 2.713 |
| 평균 출력 토큰 | 126.43 | 125.89 | 139.58 |
| 빈 답변 / length 중단 | 0 / 0 | 0 / 0 | 0 / 0 |
| 거절 문구 검출 | 13 | 15 | 19 |
| 조항 인용 미검출 | 2 | 2 | 2 |
| 문맥에서 번호가 발견되지 않는 인용 | 1 | 4 | 1 |

인용 검사는 번호 존재 여부 휴리스틱이며 번호가 맞아도 주장을 뒷받침하지 않을 수 있다.
거절 문구 건수는 오거절 판정이 아니다. 최대 관측 생성 입력은 3,086 tokens였다.

동일 입력 대조에서 A/B 68쌍 중 35쌍, B/C 39쌍 중 24쌍의 답변 문자열이 달랐다. seed가 같아도
실행 결과는 완전히 결정적이지 않았다. 단일 실행의 작은 점수 차이를 intent에 귀속하면 안 된다.

메모리 관측(peak 아님):

- 실행 전 GPU 전체 2,470 MiB / 8,192 MiB, 호스트 RAM 여유 5.67 GiB.
- Qwen /api/ps size_vram 3,178,149,969 bytes (표시 약 3.2 GB), 100% GPU.
  생성 도중 GPU 전체 5,579~5,783 MiB, 호스트 RAM 여유 0.98 GiB 관측.
- Qwen 해제 직후 GPU 전체 2,522 MiB, 호스트 RAM 여유 9.60 GiB.
- EXAONE 약 5.2 GB / 100% GPU, 채점 중 GPU 전체 7,754 MiB, RAM 여유 8.79 GiB 관측.
- 최종 완료 후 Ollama 실행 모델 목록은 비어 있으며 GPU 전체 2,692 MiB를 관측했다.
- 다른 앱의 메모리 변화가 섞인 호스트 전체 값이므로 모델 단독 RAM 요구량으로 해석하지 않는다.

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

다음 판단에는 점수 차이가 갈린 문항의 독립 검수와 동일 입력 반복 실행이 우선 필요하다.
이 결과를 근거로 현재 분류기나 운영 프롬프트를 변경하지 않았다.

로컬 산출물 SHA-256 (`reports/local-judge/intent-ablation/intent-abc-20260908/`):

```text
contexts.jsonl:            40b4a11ffd33ff56bb0a72984f438ee67fbee3b09ba7e2f3cd35b416d6aa05f4
answers.jsonl:             6d8ace5620a2a8a6e7c2b12aa3f19f3b745b9aa5c4bf77de89dd1d92dbd10614
judgments-schema-v2.jsonl: 2ed58c9ba24976cba22400b284f4426647244b2d067fbde68548f808cb9e4c56
summary-schema-v2.json:    db564c95919c040aa47c68f1f966068a54ccbdfe5f7629a8fac96a19baabee32
```

설계: [고정 문맥 실험 설계](../superpowers/specs/2026-09-08-intent-ablation-design.md).
관련 기준선: [intent 정확도 측정](2026-09-08-intent-classification-accuracy.md).
