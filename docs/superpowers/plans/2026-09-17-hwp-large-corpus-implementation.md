# HWP 대규모 코퍼스 구현 계획 (2026-09-17)

1. HWP CLI v0.17.0 실행 파일의 릴리스 해시를 검증하고, 작은 규정 샘플의 생성·추출 왕복을 확인한다.
2. 실패 재현 테스트를 먼저 작성한다: 문서 형식 발견, HWP 제목 정규화, 비구조 파일 거부, 배치 경계, 문서별 parent 중복 제거.
3. HWP 읽기 어댑터와 혼합 형식 수집을 구현한다. 외부 명령은 인자 배열로 호출하고 제한 시간을 둔다.
4. 합성 규정 사양에서 HWP 파일을 생성하는 재현 가능한 CLI를 구현한다. 기본 출력은 Git에서 제외한다.
5. 1,000개 문서 생성·구조 왕복 검사와 소규모 색인 검증을 실시한다. Docker/Ollama가 가용하지 않으면 차단 원인을 기록한다.
6. `docs/portfolio/2026-09-17-hwp-large-corpus.md`에 Before/Why/Solution/Verification/After, 원시 측정 위치와 한계를 적는다.
7. 파일별 diff, `git diff --check`, 관련 검증, AGENTS.md의 Docker 명령을 수행하고 커밋·push·PR을 연다.
