# 승격 게이트가 실제로 규칙을 강제하도록 수정

## 한 줄 결론

A/B 승격 판정을 기계적으로 내리려고 만든 게이트가 **판정을 항상 `hold`로 고정 출력**하고
있었고, 완전성·변조 검사 세 곳에 우회 경로가 있었다. 게이트 CLI 전체 경로를 도는 테스트
6개를 먼저 작성해 실패를 확인한 뒤 고쳤다. **기록된 수치와 "A 승격 보류" 결론은 바뀌지
않는다.** 바뀐 것은 그 결론을 보증하는 장치다.

## Before / 문제

`docs/portfolio/2026-09-09-intent-ab-promotion-review.md`는 승격 판정을 사람의 인상이 아니라
사전 고정 조건으로 내리기 위해 게이트를 도입했다고 기록했다. 조건은 셋이다.

```text
1. B에는 없는 critical 오류가 A에 새로 나타나면 안 된다
2. 입력이 실제로 다른 반복 실험에서 A가 진 적이 없고 최소 한 문항은 개선돼야 한다
3. 대표성 있는 독립 확인이 있어야 한다
```

코드 리뷰에서 이 게이트가 조건대로 동작하지 않는다는 지적이 나왔다. 확인한 결함은 다섯이다.

### ① 판정이 상수였다

```python
def promotion_gate(history, boundary, expected, *, confirmation=False):
    ...
    if not confirmation:
        reasons.append("representative_independent_confirmation_not_available")
    return {"decision": "hold" if reasons else "eligible", ...}
```

`main()`은 위치 인자 셋만 넘기고 `confirmation`을 줄 CLI 플래그가 없었다. 따라서 critical
0건, 승리 다수, 검토 100% 완료여도 항상 `hold`가 나왔다. `eligible` 분기는 테스트에서만
도달했다. 이번 판정이 옳았던 것은 게이트가 판단해서가 아니라 출력이 고정이었기 때문이다.

### ② 기대 명단이 봉인 밖에 있었다

게이트는 검토 대상 artifact를 SHA-256으로 검증하지만, **무엇을 검토했어야 하는지를 정의하는**
`contexts.jsonl`은 검증하지 않았다.

```python
contexts = read_jsonl(path / "contexts.jsonl")          # 해시 검증 없음
expected = {(x["case"]["id"], r) for x in contexts for r in range(3)}
```

`manifest.json`에 `contexts_sha256`이 이미 있고 `generate` 단계는 검사한다. 게이트만 빠져
있었다. 명단을 4건에서 1건으로 줄이면 `expected`가 12쌍에서 3쌍이 되고, 3쌍만 검토해도
`missing_reviews`가 빈 배열로 나온다. 문서의 "12/12쌍 존재" 주장을 검토자가 축소할 수 있었다.

### ③ 검토 파일 삭제가 감지되지 않았다

`read_jsonl`은 없는 파일에 빈 리스트를 돌려준다. 완전성 검사(`seen`)는 `stage == "boundary"`
일 때만 채워지므로 historical 단계는 개수 제약이 없었다.

```text
historical-review.jsonl 삭제 -> history = [] -> new_critical_failures: []
                             -> "11쌍 검토, 회귀 없음" 과 구분 불가
```

승격을 막은 근거인 q11(B 우세 유일 사례)이 historical에 있다. 그 파일이 사라져도 게이트는
오류 없이 통과한다.

### ④ 판정 스위치를 사람이 손으로 적었다

```python
if not row["input_equal"]:
    wins   += row["A"]["pass"] and not row["B"]["pass"]
    losses += row["B"]["pass"] and not row["A"]["pass"]
```

`input_equal`은 조건 2의 승패를 집계할지 결정하는 유일한 필드다. 두 arm의 프롬프트가 같은데
답이 달랐다면 그것은 지시문 효과가 아니라 생성 변동이며, 개선으로 세면 안 된다. 그런데 이
값이 검토자가 리뷰 파일에 직접 쓰는 boolean이었다. 양쪽 프롬프트는
`contexts.jsonl`의 `prompts["no_intent"]` / `prompts["predicted_intent"]`에 해시 검증된
상태로 이미 저장돼 있어 계산이 가능했다.

### ⑤ 게이트 CLI에 테스트가 0개였다

기존 테스트 5개는 `promotion_gate()`와 `generate_pairs()`를 순수 함수로만 호출한다.
`main()`의 `stage == "gate"` 블록(해시 검증, 경로 봉쇄, 기대 명단 생성)은 한 줄도 실행되지
않았다. ①~④가 전부 그 블록에 있거나 거기로 흘러든다. AGENTS.md 개발 규칙 2번 위반이며,
포트폴리오 문서는 "artifact 변조를 검증"을 검증된 동작으로 인용하고 있었다.

## Why / 분석

다섯 결함의 공통 원인은 하나다. **게이트가 "사람이 결과를 보고 정하는 것"을 막으려고
만들어졌는데, 정작 게이트 자신의 입력에는 같은 불신을 적용하지 않았다.**

- 검토 대상(답변 artifact)은 봉인했지만 검토 명단(`contexts.jsonl`)은 봉인하지 않았다.
- 검토 기록의 존재를 가정했고, 부재를 "이상 없음"으로 읽었다.
- 계산 가능한 값(`input_equal`)을 사람 입력으로 받았다.

수정 원칙을 하나로 잡았다. **사람이 적은 값은 믿지 않고 봉인된 데이터로 검산한다.**

판단이 갈린 지점이 하나 있었다. `promotion_gate`에 "historical이 비면 불합격" 규칙을 넣는
것이 의미상 더 옳지만, 기존 테스트
`test_only_complete_confirmed_no_regression_result_can_qualify`가 `history=[]`에서
`eligible`이 나오는 것을 의도적으로 검증한다. 남의 테스트를 이쪽 변경에 맞춰 고치는 대신
순수 함수의 계약은 두고 **CLI 단계에서 부재·공백을 거부**했다. 보고된 결함(파일 삭제가
정상 통과)은 이것으로 닫힌다.

## Solution / 구현

```text
scripts/review_intent_ab.py
  require_reviews()      파일 부재 -> FileNotFoundError, 빈 파일 -> ValueError
  verify_input_equal()   봉인된 프롬프트로 검산, 불일치 시 ValueError
  gate 분기              manifest.json 의 contexts_sha256 검증 추가
                         expected 를 manifest["repeats"] 로 생성
                         confirmation=bool(args.confirmed_by) 전달
                         promotion.json 에 confirmed_by 기록
  --confirmed-by         독립 확인의 출처를 받는 CLI 플래그
  generate 분기          repeats=meta["repeats"] (하드코딩 3 제거)

tests/test_review_intent_ab.py
  신규 6건. 게이트 CLI 전체 경로를 tmp_path 위에서 실행한다.
```

`--confirmed-by`를 단순 boolean이 아니라 **출처 문자열**로 받은 이유는, 조건 3이 자기신고인
이상 누가/무엇이 확인했는지가 `promotion.json`에 남아야 나중에 검증 가능하기 때문이다.

## Verification

AGENTS.md 증거 규칙 8번에 따라 Before는 실패하는 테스트, After는 같은 테스트의 통과다.

구현 전 (RED):

```text
$ python3 -m pytest tests/test_review_intent_ab.py -q
6 failed, 5 passed

FAILED test_gate_rejects_frozen_contexts_that_no_longer_match_the_manifest
FAILED test_gate_fails_when_a_review_file_is_missing_instead_of_reading_it_as_empty
FAILED test_gate_fails_when_a_review_file_is_empty
FAILED test_gate_recomputes_input_equal_from_the_frozen_prompts
FAILED test_gate_takes_the_repeat_count_from_the_manifest
FAILED test_gate_holds_without_confirmation_and_records_who_confirmed_with_it
```

`test_gate_takes_the_repeat_count_from_the_manifest`의 실패 출력에 `expected_pairs: 3`이
찍혔다. manifest가 `repeats: 2`인데 게이트가 3을 기대한 것으로, 하드코딩이 그대로 드러났다.

구현 후 (GREEN):

```text
$ python3 -m pytest tests/test_review_intent_ab.py -q
11 passed
```

회귀 확인 — 같은 명령을 변경 전후로 실행해 비교했다.

```text
변경 전 (e2b0094)   42 failed, 282 passed, 1 skipped
변경 후 (5c7d20d)   42 failed, 288 passed, 1 skipped
```

실패 42건은 변경 전후가 동일하다. 원인은 이 환경의 의존성 부재이며 이 변경과 무관하다.

```text
fastapi / boto3 / google-genai / kiwipiepy 미설치
app/retrieval_search.py 의 StrEnum 은 Python 3.11 필요, 이 호스트는 3.10
```

기타:

```text
git diff --check      clean
100자 초과 줄          없음 (pyproject line-length = 100)
```

미실행:

```text
docker compose run --rm rag-api pytest -v        not measured
  이 환경에 docker 가 설치돼 있지 않다. 컨테이너 전체 스위트는 데스크탑 확인이 필요하다.

수정된 게이트로 기록된 실행 재판정                  not measured
  reports/ 는 gitignore 대상이라 이 환경에 없다.
```

## After / 결과

| 항목 | Before | After |
| --- | --- | --- |
| `eligible` 도달 가능 | 불가 (CLI 경로 없음) | `--confirmed-by` 로 가능 |
| `contexts.jsonl` 변조 | 탐지 안 됨 | `frozen context changed` 로 중단 |
| 검토 파일 삭제 | 정상 통과 | `FileNotFoundError` |
| 검토 파일 공백 | 정상 통과 | `no review records` |
| `input_equal` 불일치 | 그대로 집계 | 중단 |
| `repeats` 선언 위치 | 3곳 | 1곳 (`manifest.json`) |
| 게이트 CLI 테스트 | 0건 | 6건 |

측정된 실험 결과(39/98 정확도, A/B/C 평균, 승패 집계)는 이 변경의 영향을 받지 않는다.
게이트의 판정 결과 자체도 `hold`로 동일하다. 다만 이제 그것이 상수가 아니라 조건 3이
충족되지 않았다는 판정이다.

## 한계와 미측정

```text
1. 조건 3은 여전히 자기신고다.
   --confirmed-by 는 독립 확인이 있었다고 사람이 선언하는 값이며 코드가 검증하지 않는다.
   출처 문자열을 promotion.json 에 남겨 사후 추적만 가능하게 했다. 대표성 있는 확인
   세트를 자동 검증하는 것은 이 변경의 범위 밖이다.

2. 기록된 실행에 대한 재판정을 하지 못했다.
   reports/ 가 이 환경에 없다. 재실행 시 검토 기록의 input_equal 이 봉인된 프롬프트와
   어긋나면 이제 중단된다. 이는 검사가 작동하는 것이지 기존 결론의 무효화가 아니지만,
   실제로 어긋나는지는 확인되지 않았다.

3. promotion_gate 자체는 여전히 빈 historical 을 허용한다.
   CLI 를 거치지 않고 함수를 직접 호출하면 history=[] 로도 eligible 이 가능하다.
   기존 테스트가 그 동작을 검증하고 있어 계약을 바꾸지 않았다.

4. 코드 리뷰의 나머지 지적은 처리하지 않았다.
   judge 재개 시 모델 카탈로그 전체 비교, 2차 시도 성공 후 error 키 잔존,
   compare_intent.py 의 snapshot/release 순서, INTENTS 상수 중복,
   manifest 가 app/local_judge.py 를 안 묶는 문제, review_intent_ab.py:188 의
   top_k * 4 하드코딩이 남아 있다.

5. 컨테이너 전체 테스트가 미실행이다.
```

## 다음

```text
1. 데스크탑에서 docker compose run --rm rag-api pytest -v
2. 수정된 게이트로 기록된 실행 재판정, input_equal 검산 결과 확인
3. 한계 4번의 잔여 지적 처리 여부 결정
```

## 근거

```text
커밋   5c7d20d  fix: make the promotion gate enforce what it claims
PR     #12      https://github.com/bbungjun/onpremis_rag_chatbot/pull/12
기반   e2b0094  docs: define FDE resume evidence and latency experiment plan
코드   scripts/review_intent_ab.py  tests/test_review_intent_ab.py
관련   docs/portfolio/2026-09-09-intent-ab-promotion-review.md
실행일 2026-09-10
```
