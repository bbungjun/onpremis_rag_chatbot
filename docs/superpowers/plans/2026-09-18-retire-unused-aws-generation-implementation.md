# AWS 생성 경로 제거 구현 계획 (2026-09-18)

1. 추적 파일의 호출 경로, UI 상태, 설정, 문서와 테스트를 목록화하고 기존 테스트 기준선을 확인한다.
2. 서버·발표 비교·Streamlit의 로컬/Gemini 동작 계약을 테스트에 먼저 기록한다.
3. 사용하지 않는 클라이언트와 wrapper, endpoint, UI, 환경 변수, SDK 및 전용 테스트를 제거한다.
4. 발표용 비교 화면을 Gemini 경로에 연결하고 저장된 공급자 답변을 삭제한다.
5. 사용자 안내와 역사 문서를 정리하고, 새 포트폴리오 문서에 Before/Why/After와 검증 결과를 기록한다.
6. 전체 pytest/Ruff, 정적 검색, Docker 필수 명령, 파일별 diff 및 `git diff --check`를 확인한다. 의도한 파일만 커밋·push하고 origin/main 대상 PR을 연다.
