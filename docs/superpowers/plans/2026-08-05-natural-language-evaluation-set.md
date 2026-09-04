# Natural-language Evaluation Set Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the mixed evaluation corpus with 50 employee-natural Korean policy questions that are all answerable from the committed regulations.

**Architecture:** `datasets/eval/qa_set.jsonl` remains the only evaluator input, preserving the existing JSONL schema. Dataset-integrity assertions live with the evaluation-loader tests and derive valid parent IDs directly from `datasets/docs/regulations.md`, so a question cannot silently reference a nonexistent regulation.

**Tech Stack:** UTF-8 JSONL, Python pytest, regular-expression validation.

## Global Constraints

- Create exactly 50 records with consecutive IDs `q01` through `q50`.
- Every record uses `type: "일상어"`, contains no explicit `제NN조` article-reference wording, and has an answer supported by `datasets/docs/regulations.md`.
- Preserve the exact JSONL keys: `id`, `type`, `question`, `gold_jo`, `answer`.
- Do not change RAG retrieval, Qwen prompting, embedding, or Qdrant behavior.
- Do not stage or commit files.

---

### Task 1: Add the natural-language dataset contract

**Files:**
- Modify: `tests/test_evaluate_local_judge.py:46-72`
- Test: `tests/test_evaluate_local_judge.py`

**Interfaces:**
- Consumes: `runner.load_cases(Path("datasets/eval/qa_set.jsonl"))` and the regulation Markdown file.
- Produces: a test contract that requires 50 natural-language records, consecutive IDs, no article-reference query pattern, and valid gold parent IDs.

- [ ] **Step 1: Write the failing dataset contract test**

Add a test that loads the committed dataset, extracts article IDs from the
regulation headings, and asserts the full natural-language contract:

```python
def test_committed_evaluation_cases_are_natural_and_grounded():
    cases = runner.load_cases(Path("datasets/eval/qa_set.jsonl"))
    regulation = Path("datasets/docs/regulations.md").read_text(encoding="utf-8")
    regulation_ids = {f"jo-{number}" for number in re.findall(r"^\\*\\*제(\\d+)조", regulation, re.M)}

    assert [case.id for case in cases] == [f"q{index:02d}" for index in range(1, 51)]
    assert all(case.type == "일상어" for case in cases)
    assert all(re.search(r"제\\s*\\d+\\s*조", case.question) is None for case in cases)
    assert all(set(case.gold_jo) <= regulation_ids for case in cases)
```

- [ ] **Step 2: Run the focused test to verify RED**

Run:

```powershell
docker compose run --rm rag-api pytest -v tests/test_evaluate_local_judge.py::test_committed_evaluation_cases_are_natural_and_grounded
```

Expected: FAIL because the committed dataset still contains 76 records and
article-reference questions.

### Task 2: Replace the committed dataset with 50 grounded natural questions

**Files:**
- Modify: `datasets/eval/qa_set.jsonl`
- Modify: `tests/test_evaluate_local_judge.py:66-72`
- Test: `tests/test_evaluate_local_judge.py`

**Interfaces:**
- Consumes: the 41 current `일상어` records and the cited regulation articles.
- Produces: 50 schema-valid records accepted by `runner.load_cases`.

- [ ] **Step 1: Rewrite the dataset records**

Keep the 41 current natural-language questions, renumber them consecutively,
and add exactly these nine grounded records after them:

```json
{"id":"q42","type":"일상어","question":"연차는 최소 며칠 전에 신청해야 하나요?","gold_jo":["jo-39"],"answer":"사용하려는 날로부터 최소 3영업일 전까지 사내 근태 시스템으로 신청해야 한다."}
{"id":"q43","type":"일상어","question":"재택근무를 하려면 어떤 승인이 필요한가요?","gold_jo":["jo-37"],"answer":"직무 특성상 적용 가능하다고 인정되어 대표이사 승인을 받은 사원에게 적용된다."}
{"id":"q44","type":"일상어","question":"출장비 정산은 언제까지 해야 하나요?","gold_jo":["jo-82"],"answer":"출장 종료일로부터 5영업일 이내에 증빙 서류를 첨부한 출장비 정산서를 제출해야 한다."}
{"id":"q45","type":"일상어","question":"경비 영수증은 언제까지 제출해야 하나요?","gold_jo":["jo-64"],"answer":"거래일로부터 7영업일 이내에 증빙 서류를 전표에 첨부하여 재무팀에 제출해야 한다."}
{"id":"q46","type":"일상어","question":"개인정보가 담긴 파일을 이메일로 보내도 되나요?","gold_jo":["jo-87"],"answer":"개인정보를 외부로 전송할 때는 암호화된 통신 채널을 사용해야 하며, 이메일 첨부 파일은 비밀번호를 설정해야 한다."}
{"id":"q47","type":"일상어","question":"업무용 차량은 언제까지 신청해야 하나요?","gold_jo":["jo-79"],"answer":"이용 목적·일정·운행 구간을 적은 배차 신청서를 이용일 1영업일 전까지 총무팀에 제출해야 한다."}
{"id":"q48","type":"일상어","question":"밖에서 회사 시스템에 접속하려면 무엇이 필요한가요?","gold_jo":["jo-85"],"answer":"외부에서 사내 시스템에 접근할 때는 가상사설망(VPN)을 통한 인증을 거쳐야 한다."}
{"id":"q49","type":"일상어","question":"회사 비밀번호는 어떤 조건으로 설정해야 하나요?","gold_jo":["jo-84"],"answer":"영문·숫자·특수문자를 포함해 10자 이상으로 설정하고 90일마다 변경해야 한다."}
{"id":"q50","type":"일상어","question":"보존 기간이 끝난 문서는 바로 버려도 되나요?","gold_jo":["jo-75"],"answer":"부서장 확인과 총무팀의 폐기 심의를 거쳐 복원이 불가능한 방식으로 폐기하고 폐기확인서를 작성해야 한다."}
```

Retain all required JSONL keys on every prior natural-language row and remove
every prior row whose type is `조항용어`.

- [ ] **Step 2: Update the count regression test**

Replace the old 76-case expectation with:

```python
assert len(cases) == 50
assert len({case.id for case in cases}) == 50
assert cases[0].id == "q01"
assert cases[-1].id == "q50"
```

- [ ] **Step 3: Run the focused evaluator tests to verify GREEN**

Run:

```powershell
docker compose run --rm rag-api pytest -v tests/test_evaluate_local_judge.py tests/test_export_rag_eval_answers.py
```

Expected: all focused tests pass.

### Task 3: Verify the delivered corpus

**Files:**
- Verify: `datasets/eval/qa_set.jsonl`
- Verify: `tests/test_evaluate_local_judge.py`

**Interfaces:**
- Consumes: the delivered JSONL corpus and its automated contract.
- Produces: evidence that the corpus is parseable, grounded, and ready for a
  subsequent actual-RAG run.

- [ ] **Step 1: Print a compact corpus audit**

Run:

```powershell
docker compose run --rm rag-api python -c "from pathlib import Path; from scripts.evaluate_local_judge import load_cases; cases=load_cases(Path('datasets/eval/qa_set.jsonl')); print(len(cases)); print({case.type for case in cases}); print(cases[0].id, cases[-1].id)"
```

Expected output: `50`, `{'일상어'}`, and `q01 q50`.

- [ ] **Step 2: Inspect the intended diffs and leave them unstaged**

Run:

```powershell
git diff --check
git diff -- datasets/eval/qa_set.jsonl tests/test_evaluate_local_judge.py
git status --short datasets/eval/qa_set.jsonl tests/test_evaluate_local_judge.py
```

Expected: no whitespace errors; only intentional dataset and test changes;
no `git add` or `git commit`.
