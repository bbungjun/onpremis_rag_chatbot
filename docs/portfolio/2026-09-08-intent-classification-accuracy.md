# 규칙 기반 intent 분류 정확도 기준선

## 한 줄 결론

기존 98문항에 별도 gold intent를 부여해 현재 규칙 기반 분류기를 측정한 결과 정확도는
**39/98(39.8%)**였다. `GENERAL_QA`로 분류된 68건 중 실제 gold가 `GENERAL_QA`인 질문은
16건(23.5%)뿐이었고, 나머지 52건은 특화 intent를 놓친 경우였다. 다만 gold는 구현 에이전트
한 명이 작성했으며 독립적인 사람 검수는 거치지 않았으므로 개발 기준선으로만 사용한다.

## Before / 문제

기존 평가는 `GENERAL_QA` 비율 69.4%만 측정했다. 이 값은 특화 답변 지시문을 받지 못하는
비율을 보여 주지만 분류 정확도는 아니다.

```text
GENERAL_QA가 정답인 예   "출장비 관련해서 궁금한 게 있어요"
GENERAL_QA가 오답인 예   "월급은 매달 며칠에 들어오나요?" -> deadline_lookup
특화 intent가 오답인 예  "법인카드로 개인 용도 결제하면 어떻게 되나요?"
                         procedure_lookup으로 잡히지만 실제 요청은 제재 결과 조회
```

따라서 `GENERAL_QA`를 모두 실패로 간주할 수도 없고, 특화 intent가 반환됐다는 사실만으로
성공이라고 볼 수도 없었다.

## Why / 평가 설계

현재 분류기가 반환하는 값을 gold로 복사하지 않고, 질문의 주된 정보 요구와 해당 질문에
도움이 되는 canonical prompt를 기준으로 별도 라벨을 작성했다.

```text
deadline_lookup    시점, 기한, 기간, 주기, 날짜 조회
eligibility_check  구체적 행동·상황이 허용되거나 기준을 충족하는지 판정
procedure_lookup   처리 단계, 채널, 검토자, 승인자, 보고 경로
requirement_lookup 필수 조건, 증빙, 서류, 설정 요건
general_qa         위 네 지시문 밖의 사실·수량·결과 조회 또는 의도가 불명확한 질문
```

질문 하나에 여러 요소가 있으면 문장에 직접 표현된 주 요청 하나를 선택했다. 모호하게
변형된 질문은 원본이 특화 intent였더라도 `general_qa`가 정답일 수 있다.

라벨은 `datasets/eval/intent_gold.jsonl`에 분리했다. 기존 검색 평가 데이터의 schema를
바꾸지 않고, classifier 출력과 평가자의 기대값을 명확히 분리하기 위한 선택이다.

`intent_robustness.jsonl`의 `base_id`는 라벨 상속에 사용하지 않았다. 이 값 중 일부는
교체되기 전 76문항 데이터셋 ID를 가리켜 현재 50문항 파일과 일치하지 않기 때문이다.
robustness 질문 48건도 문장 자체를 기준으로 독립적으로 라벨링했다.

## Solution / 구현

`scripts/eval_intent.py`에 다음을 추가했다.

```text
load_gold_labels      ID 중복, 누락, 허용되지 않은 intent 검증
evaluate_accuracy     전체/유형별 정확도, confusion matrix, 오분류 목록 계산
print_accuracy_report 정확도와 non-zero confusion, 선택적 오분류 출력
--gold                gold JSONL 입력
--list-errors         모든 오분류 질문 출력
```

기존 coverage 출력과 `--list` 동작은 유지했다. 평가 케이스 ID가 중복되거나 gold 라벨이
없으면 측정을 중단해 일부 데이터만 조용히 채점되는 것을 방지했다. 커밋된 gold 라벨이
현재 두 데이터셋의 98개 ID를 정확히 덮는 계약 테스트도 추가했다.

분류기 `app/question_interpreter.py`는 변경하지 않았다. 이번 측정값은 개선 후 결과가 아니라
현재 동작의 기준선이다.

## Verification

TDD 확인:

```text
docker compose run --rm rag-api pytest -q tests/test_eval_intent.py
-> 구현 전 ImportError: evaluate_accuracy 없음
-> gold 파일 추가 전 FileNotFoundError: intent_gold.jsonl 없음
-> 구현 및 데이터 추가 후 14 passed
```

전체 회귀 및 런타임 확인:

```text
docker compose run --rm rag-api pytest -v
-> 319 collected, 317 passed, 2 skipped, 0 failed (6.58s)

curl http://localhost:6333
-> Qdrant 1.18.2 정상 응답

docker compose run --rm rag-api python -m app.healthcheck
-> qwen3:4b-instruct, think=off, Qdrant URL/collection 설정 출력 정상

docker compose run --rm rag-api python -m compileall -q scripts/eval_intent.py
-> 통과
```

스킵 2건은 Docker 이미지에 git CLI가 없어 실행되지 않은 endpoint 노출 검사 1건과,
`RUN_EXAONE_LIVE_TEST=1`이 필요한 실제 EXAONE 테스트 1건이다. 정확도 측정 경로의 실패는 없다.

측정 명령:

```text
docker compose run --rm rag-api python scripts/eval_intent.py \
  datasets/eval/qa_set.jsonl datasets/eval/intent_robustness.jsonl \
  --gold datasets/eval/intent_gold.jsonl --list-errors
```

실행 조건:

```text
실행일       2026-09-08
기준 코드   main d8ec28a에서 분기
분류기       문자열 마커 31개 + 조건 추출 규칙
qa_set       50건, SHA-256 1c9fb38eda3ce4ff01537792dbbf39178b93388fe4d5ef69257488ab587b7ae8
robustness   48건, SHA-256 6d7fb082a9ac5aed847c0bf0bbdaad0b3de57c26088bc69278862b27cb490623
gold         98건, SHA-256 8b4ae5b062eab8f9b42a5c96b6080da6ec77f0fdd3eded017581f012d93269ed
외부 모델    사용하지 않음
```

## After / 측정 결과

전체 정확도:

```text
39/98 = 39.8%
오분류 59건
```

입력 유형별:

| 유형 | 정확도 |
| --- | ---: |
| 정상 표기(일상어) | 21/50 (42.0%) |
| 붙여쓰기 | 2/12 (16.7%) |
| 오타 | 2/12 (16.7%) |
| 구어체 | 4/12 (33.3%) |
| 애매 | 10/12 (83.3%) |

애매 질문의 점수가 높은 것은 적극적인 의도 인식이 잘 된 결과가 아니다. gold에서 의도가
불명확한 질문을 `general_qa`로 두었고 현재 분류기도 대부분 fallback했기 때문이다.

Gold intent별 confusion:

| expected | support | correct | 주요 오분류 |
| --- | ---: | ---: | --- |
| deadline_lookup | 39 | 8 (20.5%) | general_qa 30, eligibility_check 1 |
| eligibility_check | 18 | 10 (55.6%) | general_qa 8 |
| procedure_lookup | 10 | 1 (10.0%) | general_qa 9 |
| requirement_lookup | 11 | 4 (36.4%) | general_qa 5, procedure_lookup 2 |
| general_qa | 20 | 16 (80.0%) | procedure_lookup 4 |

가장 큰 실패는 특화 intent를 `general_qa`로 놓치는 경우다. 전체 오분류 59건 중 52건
(88.1%)이 이 유형이다. 현재 `general_qa` 예측 68건의 precision은 16/68(23.5%)다.

관찰된 원인:

```text
deadline 마커가 좁음   "언제", "며칠 안에", "며칠 전에", "얼마나 자주"를 놓침
procedure 마커가 좁음  "누구한테", "누가 결재", "어떤 단계"를 놓침
오타 복구 없음         "언재", "몇칠", "잇나요"가 기존 마커와 일치하지 않음
부분 문자열 오탐       "받게 되나요"가 eligibility의 "되나요"에 걸림
표면 표현 우선         결과 조회의 "어떻게 되나요"가 procedure로 분류됨
```

## Evidence and Limitations

1. Gold 라벨은 구현 에이전트 한 명이 정책을 정의하고 작성했다. 독립적인 사람 annotator의
   검수나 annotator 간 일치도 측정이 없으므로 39.8%는 잠정 개발 기준선이다.
2. 98문항은 기존 개발 평가 자료이며 실제 사용자 로그나 별도의 held-out intent 세트가 아니다.
3. 붙여쓰기·오타·구어체·애매 질문은 손으로 만든 변형이다. 실제 입력 분포를 대표하지 않는다.
4. 정확도는 intent 분류만 측정한다. 검색 Recall, 최종 답변 정확도, 지연 변화는 측정하지 않았다.
5. 하나의 primary intent만 허용했다. 복합 질문과 경계 사례에서는 다른 라벨도 합리적일 수 있다.
6. 이번 작업에서 분류 규칙을 고치지 않았다. 다음 변경은 같은 gold와 명령으로 재측정하되,
   이 개발 세트에 과적합하지 않도록 별도 held-out 질문이 필요하다.
