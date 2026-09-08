# 의도 분류 커버리지 측정

## 한 줄 결론

`app/question_interpreter.py`의 의도 분류가 질문 98건 중 **69.4%를 `GENERAL_QA`로
떨어뜨린다**는 기준선을 처음으로 측정했다. 검색 경로는 영향을 받지 않으며 잃는 것은
의도별 답변 지시문이다. 이번 작업은 측정만 했고 분류기는 고치지 않았다.

## Before / 문제

`app/question_interpreter.py`는 RAG 파이프라인의 첫 단계로, 사용자 질문을
`retrieval_question`(검색용)과 `canonical_question`(답변 지시문 포함)으로 나눈다.
이때 `intent`가 다섯 값 중 하나로 정해지고, 그 값이 `canonical_question`에 붙일 지시문을
고른다.

`intent`가 `GENERAL_QA`이면 지시문을 붙이지 않고 원문을 그대로 반환한다.

```python
if intent == GENERAL_QA:
    return original_question
```

문제는 **이 분기에 얼마나 자주 빠지는지 측정된 적이 없었다**는 것이다. 저장소에는
`tests/test_question_interpreter.py` 17건이 있었지만 전부 표기가 정확한 질문이었고,
오타·구어체·붙여쓰기 오류 케이스가 0건이었다.

재현 (2026-09-08, `main` = `bb46733`):

```text
python3 -c "from app.question_interpreter import interpret_question as f; \
            print(f('연차 좀 쓰고 싶은데').intent)"
-> general_qa
```

영향 범위는 답변 지시문에 한정된다. 확인 결과 `intent`를 읽는 코드는 저장소 전체에서
세 곳뿐이고 검색 경로에는 하나도 없다.

```text
바뀌는 것    canonical_question 한 필드
안 바뀌는 것 retrieval_question, dense 임베딩, BM25, RRF 검색, parent 확장,
             system prompt, context 주입, 생성 호출, sources 반환
```

따라서 이 수치는 검색 품질 저하가 아니라 **답변 지시 커버리지**를 뜻한다. 분류에
실패해도 동작이 깨지지 않고 일반적인 RAG 로 격하된다.

## Why / 분석

분류 장치는 두 가지뿐이다.

```python
def _contains_any(text: str, markers: tuple[str, ...]) -> bool:
    return any(marker in text for marker in markers)   # 부분 문자열 포함 검사
```

```text
1. 마커 문자열 31개의 부분 문자열 포함 검사
2. 조건 추출 성공 여부 ("lead_time" in conditions)
```

임베딩도 학습된 분류기도 LLM 호출도 없다. 온프레미스에서 질의당 추가 모델 호출을
늘리지 않으려는 선택이며, 대가는 커버리지다.

구조상 예상되는 실패 양상은 넷이다.

```text
오타가 마커 안에 나면 실패     "몇칠 전까지" != 마커 "며칠 전까지"
단어 경계를 보지 않음          "불가능" 안의 "가능" 이 매칭된다
마커 밖 표현은 전부 GENERAL_QA "연차 좀 쓰고 싶은데" 는 31개 중 0개 적중
첫 매치가 이김                 "절차는 어떻게 되고 며칠 전까지" -> deadline_lookup 만
```

`_normalize_retrieval_question`이 붙여쓰기를 일부 복구하지만 치환 규칙이 8개뿐이라
`연차 신청` `출장비 정산` `경비 처리` `재택근무 승인` 밖의 용어는 손대지 못한다.

측정 방법으로 세 가지를 검토했다.

```text
A. 기존 qa_set.jsonl 로만 측정
   장점: 추가 데이터 없이 즉시 가능. 단점: 오타·구어체 케이스가 없어 취약성을 못 본다.
B. 새 평가 세트를 처음부터 작성
   장점: 원하는 분포 확보. 단점: 질문을 지어내게 되어 실제 사용자 분포와 무관해진다.
C. 기존 질문에서 변형을 파생 (채택)
   장점: 원문이 실재하고 base_id 로 추적 가능. 오타·구어체 분포를 통제할 수 있다.
   단점: 실제 사용자 로그가 아니라 손으로 만든 변형이다.
```

C를 택했다. 근거 없는 질문을 만들지 않으면서 취약성 축을 통제할 수 있고, 각 변형이
어느 원본에서 왔는지 문서 없이 데이터만 봐도 확인되기 때문이다.

## Solution / 구현

측정 도구와 평가 세트를 추가했다. 분류기 자체는 수정하지 않았다.

```text
scripts/eval_intent.py                  측정 CLI. load_cases / summarize 는 순수 함수로
                                        분리해 파일 I/O 없이 테스트할 수 있게 했다.
tests/test_eval_intent.py               파싱·집계 테스트 6건. 구현 전 실패를 확인했다.
datasets/eval/intent_robustness.jsonl   변형 질문 48건.
app/question_interpreter.py             함수 단위 docstring. 실행 코드 변경 없음(+110/-0).
```

평가 세트는 `datasets/eval/qa_set.jsonl`의 질문에서 파생하고 `base_id`로 원본을 가리킨다.

```json
{"id": "r05", "base_id": "q37", "type": "붙여쓰기",
 "question": "1년동안80%이상출근한사람은연차가며칠생기나요?"}
```

유형은 붙여쓰기 / 오타 / 구어체 / 애매 각 12건이다. 초안은 유형당 4건이었으나 비율을
말하기에 표본이 부족해 12건으로 늘렸다. 실제로 표본을 늘리자 `애매` 유형이 100.0%에서
91.7%로 바뀌어, 4건짜리 100%가 의미 없는 수치였음이 드러났다.

`summarize`는 전체와 `type`별 집계를 함께 낸다. 유형별로 나누지 않으면 어떤 입력
특성에서 무너지는지 보이지 않기 때문이다.

## Verification

실행 조건:

```text
실행일        2026-09-08
기준 커밋     bb46733 (origin/main)
분류기        app/question_interpreter.py (마커 31개, 정규화 규칙 8개)
평가 데이터   datasets/eval/qa_set.jsonl              50건 (전부 일상어)
              datasets/eval/intent_robustness.jsonl   48건 (붙여쓰기/오타/구어체/애매 각 12)
외부 의존성   없음. 이 경로는 re 와 dataclasses 만 사용하므로 Ollama/Qdrant 불필요.
```

측정 명령:

```bash
python3 scripts/eval_intent.py datasets/eval/qa_set.jsonl datasets/eval/intent_robustness.jsonl
python3 scripts/eval_intent.py datasets/eval/intent_robustness.jsonl --list
```

자동화 테스트:

```text
pytest tests/test_eval_intent.py tests/test_question_interpreter.py  -> 23 passed
pytest tests/test_eval_intent.py tests/test_question_interpreter.py \
       tests/test_chunking.py                                        -> 34 passed
git diff --check                                                     -> clean
```

미실행:

```text
docker compose run --rm rag-api pytest -v   not measured
  호스트에 qdrant_client 와 kiwipiepy 가 없어 컨테이너 전체 스위트는 돌리지 못했다.
```

## After / 결과

이전 측정값이 없으므로 Before/After 비교가 아니라 **기준선 수립**이다. 개선 폭을
주장하지 않는다.

| 데이터셋 | 질문 수 | `GENERAL_QA` |
| --- | --- | --- |
| `datasets/eval/qa_set.jsonl` | 50 | 56.0% |
| `datasets/eval/intent_robustness.jsonl` | 48 | 83.3% |
| 합산 | 98 | **69.4%** |

`intent_robustness.jsonl` 유형별:

| 유형 | `GENERAL_QA` |
| --- | --- |
| 애매 | 11/12 (91.7%) |
| 붙여쓰기 | 10/12 (83.3%) |
| 오타 | 10/12 (83.3%) |
| 구어체 | 9/12 (75.0%) |

표기가 정확한 `qa_set.jsonl` 50건에서도 56.0%가 분류에 실패한다. 즉 커버리지 문제는
오타·구어체에서만 생기는 것이 아니라 정상 표기 질문에서도 절반 넘게 발생한다.

전체 intent 분포 (98건):

```text
general_qa          68   69.4%
eligibility_check   11   11.2%
deadline_lookup      8    8.2%
procedure_lookup     7    7.1%
requirement_lookup   4    4.1%
```

의도별 답변 지시문 분리 기능이 **30.6%에서만 작동한다.**

## 한계와 미측정

```text
1. 답변 품질 영향을 측정하지 않았다.
   GENERAL_QA 일 때 지시문이 빠진다는 것은 코드로 확인했으나, 그래서 답변이 실제로
   나빠지는지는 재지 않았다. 같은 질문의 분류 성공/실패 두 버전을 생성까지 돌려
   비교해야 하며, 이번에는 Ollama/Qdrant 를 띄우지 못해 not measured 다.

2. 정확도가 아니라 GENERAL_QA 비율만 잰다.
   평가 세트에 기대 intent(gold label)가 없다. 따라서 "분류가 맞았는가"는 알 수 없고
   "분류를 포기했는가"만 알 수 있다. 오분류 사례는 별도로 관찰됐다. 예를 들어
   "회식비는 얼마까지 처리되나요?"는 조회 질문인데 "되나요" 때문에 eligibility_check
   로 분류된다. 이런 건 이 수치에 잡히지 않는다.

3. 변형 48건은 손으로 만든 것이다.
   원문은 실재하고 base_id 로 추적되지만, 변형 자체는 실제 사용자 입력 로그가 아니다.
   실제 오타 분포와 다를 수 있다.

4. 유형당 12건은 비율을 말하기에 최소 수준이다.
   유형 하나를 근거로 결론을 내리려면 표본을 더 늘려야 한다. 초안 4건에서 12건으로
   늘렸을 때 애매 유형이 100.0% -> 91.7% 로 움직인 것이 그 근거다.

5. 컨테이너 전체 테스트가 미실행이다.
   docker compose run --rm rag-api pytest -v 는 데스크탑 환경에서 확인이 필요하다.

6. PR #9 커밋 메시지의 수치는 폐기된 데이터셋 기준이다.
   79ccd48 과 6e68f2d 는 로컬이 origin/main 보다 30커밋 뒤처진 상태에서 작성되어,
   03e84df "test: replace article-term questions with natural language eval set" 로
   교체되기 전의 qa_set.jsonl(76건, 조항용어 포함)을 측정했다. 그때 기록한
   59.2% / 68.5% / 124건은 무효다. 이 문서의 50건 / 69.4% / 98건이 현재 main 기준의
   유효 수치다.
```

## 다음 실험

기준선이 생겼으므로 변경 후 같은 명령으로 재측정해 비교할 수 있다.

| 안 | 내용 | 포기하는 것 |
| --- | --- | --- |
| A | 마커 목록 확장 | 정밀도. 이미 관찰된 `회식비...되나요` 오분류가 늘어날 수 있다 |
| B | 규칙 실패 시에만 소형 LLM 분류 | 온프레미스 지연. 애매한 질문일수록 느려진다 |
| C | 현행 유지, 한계만 문서화 | 커버리지 개선 없음. 검색은 이미 정상이다 |

어느 쪽이든 착수 전에 한계 1번(답변 품질 영향)을 먼저 측정해야 한다. 지시문이 없어도
답변 품질이 유지된다면 69.4%는 고칠 필요가 없는 수치다.

## 근거

```text
커밋   79ccd48  feat: measure intent classification coverage
       6e68f2d  docs: record intent coverage baseline and next steps
PR     #9       https://github.com/bbungjun/onpremis_rag_chatbot/pull/9 (merged)
데이터  datasets/eval/qa_set.jsonl              50건
       datasets/eval/intent_robustness.jsonl   48건
코드   app/question_interpreter.py  scripts/eval_intent.py  tests/test_eval_intent.py
```
