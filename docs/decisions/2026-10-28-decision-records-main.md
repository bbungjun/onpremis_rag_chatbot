# 의사결정 기록의 main 반영

## D01 — 요청과 반영 범위

- 요청: 어제 추가한 기록을 main에 반영하고 파일 소유권 목록의 의미를 설명한다.
- Before: main `f970ee8af4e97dba041e2184189faaebf6b72b41`에는 결정 기록 규칙과
  `docs/decisions`가 없었다. PR #21은 RAG 코드·데이터·평가 변경을 함께 포함한 Draft다.
- 대안: PR #21 전체 병합, 필요한 기록 파일만 별도 PR로 선별 반영.
- 선택: 원래 작업과 생성 품질의 채택 보류 상태를 보존하면서 기록만 분리한다.
- 가져올 소스: `dc5aa3bb5e51cc84ff08f3b9a890e82a2fa8c13f`의 AGENTS.md 결정 기록 절,
  `docs/decisions/README.md`, `docs/decisions/2026-10-27-evidence-context.md`.
- runtime 코드·테스트·데이터·설계·평가 보고서는 이번 반영 범위에 넣지 않는다.
  10월 27일 일지는 해당 실험 브랜치의 역사적 기록이며 main의 구현 상태를 뜻하지 않는다.
- README에 이 구분을 명시하고 이번 선별 반영의 결정·검증도 새 일지로 남긴다.
- After 계획: 문서 전용 브랜치의 실제 diff와 검증을 확인하고 main 대상 PR을 병합한다.
  사용자의 main 반영 요청이 병합 승인이다. 추가 배포나 PR #21 전체 병합은 수행하지 않는다.

## D02 — 파일 소유권 목록의 의미

- 목록은 동시에 여러 작업자를 투입할 때 역할별 수정 범위를 정하는 협업 규칙이다.
  예: 청킹 담당은 `app/chunking.py`와 `tests/test_chunking.py`를 한 묶음으로 맡는다.
- Windows 파일 소유자·접근 권한, Git 작성자, CODEOWNERS의 자동 리뷰 설정이 아니다.
  파일에 영구적으로 특정 AI가 배정됐다는 뜻도 아니다.
- 다른 담당자가 수정 중인 파일이 필요하면 일방적으로 덮어쓰지 않고 의존성을 조율한다.
- 현재 문구는 정적 모듈 목록이며 단독/순차 작업과 활성 담당자 배정 기준이 충분히
  명시돼 있지 않다. 이번 요청은 설명이므로 목록과 중단 규칙 자체는 수정하지 않는다.

## D03 — 검증 및 게시 계획

- AGENTS.md 변경은 결정 기록 절 11줄로 제한하고 다른 제품 규칙은 그대로 보존한다.
- 과거 일지의 내용은 원본 소스와 동일함을 확인한다.
- 새 문서 경로와 로컬 링크를 검사하고 `git diff --check`, 로컬 pytest, Ruff를 실행한다.
- 필수 Compose 명령은 실행 가능 여부를 별도로 기록한다. 문서 반영을 서버 검증이나
  RAG 생성 품질 개선으로 표현하지 않는다.
- CI 통과 후 main에 병합하고 원격 main의 실제 파일과 변경 범위를 확인한다.

## D04 — 문서 변경 검증

- AGENTS.md 차이는 기록 규칙 11줄 추가뿐이며, runtime 파일과 소유권 목록은 변경하지 않았다.
- 10월 27일 일지의 바이트가 원본 커밋의 파일과 동일함을 확인했다.
- Markdown 로컬 링크가 모두 존재하고 `git diff --check`를 통과했다.
- `PYTHONUTF8=1 python -m pytest -q -rs`: **338 passed, 9 skipped**.
  EXAONE live opt-in 1건과 HWP CLI 미설치 8건 생략. 이 테스트 집합은 main 기반이며,
  PR #21의 추가 평가 코드가 포함된 353개 테스트와 구분한다.
- `python -m ruff check .`, `python -m ruff format --check .` 통과.
- 필수 Compose 명령 세 개는 worktree에 `.env`가 없어 exit 1,
  `curl.exe --max-time 5 http://localhost:6333`은 exit 7이었다.
  원본 검사 결과는 git에서 제외된 `reports/retrieval-eval/decision-records-main-20261028/`에 보존했다.
- 서버 동작, RAG 성능, 생성 품질 또는 Production 반영을 검증한 작업이 아니다.
