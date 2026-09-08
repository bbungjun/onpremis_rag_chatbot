# 의도 분류 커버리지

`app/question_interpreter.py` 의 intent 분류가 실제 질문의 몇 %를 잡는지 측정한 기록과
재현 방법이다.

## 한 줄 요약

질문 124개 중 **68.5%가 `GENERAL_QA` 로 떨어진다.** 즉 의도별 답변 지시문 분리 기능이
31.5% 에서만 작동한다.

## GENERAL_QA 가 뜻하는 것

검색 실패가 아니다. RAG 는 그대로 돈다.

```text
바뀌는 것   canonical_question 하나. 지시문이 안 붙고 원문 그대로 간다.
안 바뀌는 것 retrieval_question, dense 임베딩, BM25, RRF 검색, parent 확장,
             system prompt, context 주입, Qwen 호출, sources 반환 — 전부 정상.
```

`intent` 를 읽는 곳은 코드 전체에서 세 군데뿐이고 검색 경로에는 하나도 없다.

```text
정상 분류   질문 → 검색 → 조문 → system prompt → "기한을 답하라" 지시문 → Qwen
GENERAL_QA  질문 → 검색 → 조문 → system prompt → (지시문 없음)        → Qwen
```

따라서 이 수치는 **검색 품질이 아니라 답변 지시 커버리지**다. 평범한 RAG 로 격하될 뿐
동작이 깨지지는 않는다.

## 측정 결과

| 데이터셋 | 질문 수 | GENERAL_QA |
| --- | --- | --- |
| `datasets/eval/qa_set.jsonl` | 76 | 59.2% |
| `datasets/eval/intent_robustness.jsonl` | 48 | 83.3% |
| 합산 | 124 | **68.5%** |

`intent_robustness.jsonl` 유형별:

| 유형 | GENERAL_QA |
| --- | --- |
| 애매 | 11/12 (91.7%) |
| 붙여쓰기 | 10/12 (83.3%) |
| 오타 | 10/12 (83.3%) |
| 구어체 | 9/12 (75.0%) |

`qa_set.jsonl` 유형별:

| 유형 | GENERAL_QA |
| --- | --- |
| 일상어 | 27/41 (65.9%) |
| 조항용어 | 18/35 (51.4%) |

조항 용어를 쓴 질문조차 절반이 실패한다.

## 왜 이렇게 나오나

분류 장치는 두 개뿐이다.

```python
def _contains_any(text: str, markers: tuple[str, ...]) -> bool:
    return any(marker in text for marker in markers)   # 부분 문자열 포함 검사
```

1. 마커 문자열 31개의 부분 문자열 포함 검사
2. 조건 추출 성공 여부 (`"lead_time" in conditions`)

임베딩도, LLM 호출도, 학습된 분류기도 없다. 첫 매치에서 즉시 반환하는 if 체인이라
순서가 곧 우선순위다.

알려진 실패 양상:

```text
오타가 마커 안에 나면 죽는다     "몇칠 전까지" != 마커 "며칠 전까지"
단어 경계를 모른다               "불가능" 안의 "가능" 이 매칭된다
마커 밖 표현은 전부 GENERAL_QA   "연차 좀 쓰고 싶은데" 는 31개 중 0개 적중
여러 의도가 섞이면 첫 매치만 이김  "절차는 어떻게 되고 며칠 전까지" -> deadline 만
```

정규화(`_normalize_retrieval_question`)가 붙여쓰기를 일부 고치지만 규칙이 8개뿐이라
`연차 신청` `출장비 정산` `경비 처리` `재택근무 승인` 밖은 손대지 못한다.

## 재현

호스트에서 (외부 의존성 없음, `re` 와 `dataclasses` 만 쓴다):

```bash
python3 scripts/eval_intent.py datasets/eval/qa_set.jsonl datasets/eval/intent_robustness.jsonl
python3 scripts/eval_intent.py datasets/eval/intent_robustness.jsonl --list
```

컨테이너에서:

```bash
docker compose run --rm rag-api python scripts/eval_intent.py \
  datasets/eval/qa_set.jsonl datasets/eval/intent_robustness.jsonl
```

## 평가 데이터

`datasets/eval/intent_robustness.jsonl` 48문항은 전부 `qa_set.jsonl` 의 질문에서
파생했고 `base_id` 로 원본을 가리킨다. 지어낸 질문이 아니다.

```json
{"id": "r05", "base_id": "q37", "type": "붙여쓰기",
 "question": "1년동안80%이상출근한사람은연차가며칠생기나요?"}
```

유형은 붙여쓰기 / 오타 / 구어체 / 애매 각 12문항이다. 유형당 12개는 비율을 말하기에
최소 수준이므로, 특정 유형을 근거로 결론을 내려면 더 늘려야 한다.

## 아직 안 한 것

측정만 했고 고치지 않았다. 다음 선택지는 셋이다.

| 안 | 내용 | 포기하는 것 |
| --- | --- | --- |
| A | 마커 목록 확장 | 정밀도. 이미 `회식비...되나요` -> `eligibility_check` 오분류가 있다 |
| B | 규칙 실패 시에만 소형 LLM 분류 | 온프레미스 지연. 애매한 질문일수록 느려진다 |
| C | 현행 유지, 한계만 문서화 | 커버리지 개선 없음. 다만 검색은 이미 정상이다 |

어느 쪽이든 착수 전에 이 문서의 수치를 기준선으로 잡고, 변경 후 같은 명령으로 다시
측정해 비교한다.

## 남은 검증

```powershell
docker compose up -d
docker compose run --rm rag-api pytest -v
curl http://localhost:6333
docker compose run --rm rag-api python -m app.healthcheck
```

호스트에는 `qdrant_client` 가 없어 `pytest` 전체는 컨테이너에서만 돈다. 이 작업에서
확인한 범위는 `tests/test_eval_intent.py` 와 `tests/test_question_interpreter.py` 23개다.

## 관련 파일

```text
app/question_interpreter.py             분류 구현. 이번에 함수 단위 docstring 추가
scripts/eval_intent.py                  측정 CLI. load_cases / summarize 순수 함수
tests/test_eval_intent.py               파싱·집계 테스트 6개
datasets/eval/qa_set.jsonl              기존 평가 질문 76개
datasets/eval/intent_robustness.jsonl   변형 질문 48개
```
