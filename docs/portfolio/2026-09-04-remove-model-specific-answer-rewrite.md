# 모델·질문 특화 답변 덮어쓰기 코드 제거

## 한 줄 결론

EXAONE 모델이 연차 신청 기한 질문에 부정 답변을 내면 정규식 규칙으로 답변 전체를 고정
문장으로 바꾸던 코드를 제거했다. 제거 후에도 회귀 테스트 30건이 통과하며, 2026-08-31
포트폴리오 평가 수치는 Qwen 생성 경로라 영향을 받지 않는다.

## Before / 문제

커밋 `8cd53bc` (2026-06-22, "fix: classify annual leave eligibility by structure")는
`app/rag_pipeline.py`에 `_polish_exaone_leave_deadline_answer`를 추가했다. 동작 조건은
다음 네 가지가 모두 맞을 때였다.

```text
1. LLM 모델명이 exaone 으로 시작
2. 질문 의도가 eligibility_check 이고 "연차"와 상대 기간(N일 뒤, 내일 등)이 포함
3. LLM 답변에 "불가능", "충족하지 못", "충족하지 않" 중 하나가 포함
4. 사용자가 제시한 일수가 검색된 조문에서 정규식으로 뽑은 "최소 N영업일 전" 이상
```

조건이 맞으면 LLM 답변을 버리고 파이썬 f-string으로 만든 고정 문장을 반환했다.
당시 목적은 데모에서 EXAONE이 "4일 뒤 연차"를 "3영업일 전 신청" 규정과 잘못 비교해
"불가능합니다"라고 답하는 사례를 막는 것이었다.

관찰된 문제:

```text
- 제품 규칙 "Qwen must answer from retrieved internal document chunks"를 코드가 우회한다.
  답변 본문이 LLM 출력이 아니라 애플리케이션 규칙 출력이 된다.
- 단일 질문 유형과 단일 모델에만 적용되는 규칙이 핵심 파이프라인 안에 있어,
  코드 리뷰어가 "데모용 튜닝"으로 읽을 수 있다.
- 정규식이 "최소 N영업일 전"을 잘못 잡으면 문서에 없는 숫자로 답을 만들 수 있다.
- 동일 오류가 다른 질문 유형(출장비 정산 기한 등)에서 나면 대응하지 못한다.
```

## Why / 분석

- 실제로 채택된 평가 결과(`docs/portfolio/2026-08-31-rrf-ablation-reranker-evaluation.md`)는
  답변 생성 모델이 `qwen3:4b`이고 EXAONE은 Judge로만 사용했다. 이 함수는 모델명이
  exaone일 때만 동작하므로 채택 수치와 무관하다.
- 잘못된 비교를 막는 일반적인 장치는 이미 system prompt와 질문 해석 계층에 있다.
  system prompt는 상대 기간을 달력 날짜로 계산하지 말고 문서의 최소/최대 기간과만
  비교하라고 지시하고, canonical_question은 "사용자 조건이 M 이상이면 기준을 충족"
  형태의 비교 힌트를 준다.
- 대안으로 실험 플래그 뒤에 숨기는 방법을 검토했지만, 플래그가 있어도 답변을 규칙으로
  생성한다는 사실은 같다. 문제가 재현되면 프롬프트나 평가 세트로 다루는 것이 맞다.

## Solution / 구현

제거 대상:

```text
app/rag_pipeline.py
  - EXAONE_MODEL_PREFIX, NEGATIVE_VERDICT_MARKERS 상수
  - _polish_exaone_leave_deadline_answer, _is_annual_leave_deadline_question,
    _lead_time_days, _minimum_leave_deadline_days
  - answer_question 안의 호출부
  - 더 이상 쓰지 않는 re, ELIGIBILITY_CHECK import

tests/test_rag_pipeline.py
  - 덮어쓰기 동작을 검증하던 테스트 3개 삭제
  - 추가: test_answer_question_returns_llm_answer_unchanged_for_any_model
    exaone과 qwen 모델명 모두에서 부정 답변이 원문 그대로 반환되는지 검증
```

테스트를 먼저 바꿔 실패를 확인한 뒤 코드를 제거했다.

## Verification

```text
pytest tests/test_rag_pipeline.py tests/test_rag_search_injection.py
  -> 새 테스트 추가 직후: 1 failed (덮어쓰기 코드가 남아 있어 실패)
  -> 코드 제거 후: 30 passed
ruff check app/rag_pipeline.py tests/test_rag_pipeline.py -> 통과
ruff format --check -> 통과
```

실행 환경: WSL2, Python 3.12, 2026-09-04. Ollama/Qdrant 없이 monkeypatch 기반 단위
테스트만 실행했다.

## After / 결과

- 답변은 모델과 질문 유형에 관계없이 LLM 출력 그대로 반환된다.
- 제거된 코드 63줄, 삭제된 테스트 3개, 추가된 테스트 1개.

## 한계와 미측정

- EXAONE 실사용 경로에서 "4일 뒤 연차" 질문의 답변이 제거 전후로 어떻게 달라지는지는
  이번 작업에서 실행 환경이 없어 **not measured** 다. 6월 데모에서 관찰된 "불가능합니다"
  오답이 다시 나타날 수 있다.
- 해당 사례는 후속 로드맵의 무답·공격·부분 조건 평가 세트에 `partial` 범주로 넣어
  프롬프트 수준에서 다룬다.
