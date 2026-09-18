# HWPX 입력과 구조 학습 첫 단계 (2026-09-18)

## Before / 문제

HWP CLI v0.17.0은 HWP 5.0과 HWPX를 모두 읽지만, 현재 `read_document`의 확장자 검사와 수집기의 파일 탐색은 `.hwpx`를 거부한다. 사용자가 제공한 [HWP/HWPX 파싱 글](https://dbhyeong.github.io/blog/hwp-hwpx-format-parsing-python)은 HWP의 바이너리 레코드와 HWPX의 ZIP/XML 구조를 설명한다. 그러나 본문 텍스트 노드만 모으면 표 셀 관계·자동 번호·각주 참조가 사라질 수 있어 규정 RAG의 검색 근거로 바로 사용하기 어렵다.

## Why / 선택

첫 학습 단위는 HWPX를 실제 수집 경로에 넣고, 같은 합성 규정의 HWP/HWPX 추출을 비교하는 것이다. 생산 경로의 작은 interface인 `read_document(path) -> str`을 유지하고 포맷 내부의 복잡성은 HWP CLI adapter 뒤에 둔다. 자체 HWP 5.0 레코드 파서를 쓰기 전에 HWPX 패키지와 구조 정보가 어디서 손실되는지 확인할 수 있다. 직접 XML 파싱은 표·번호·각주·이미지 관계를 보존하는 구조 모델이 정해진 다음 단계로 둔다.

## Solution / 범위

- `.hwpx`를 문서 리더와 수집 파일 탐색에 추가한다. 이미지 자산 추출과 기존 표·각주·OCR 보강을 재사용한다.
- HWPX 합성 fixture에서 표·번호 목록·각주 귀속·이미지 자산·캡션을 같은 조항에 보존하는지 통합 테스트한다.
- 읽기 전용 학습 가이드에 ZIP 엔트리·XML 텍스트 노드·HWP CLI 출력의 차이를 재현하는 명령을 기록한다.
- 비밀번호·암호화 HWPX, 독립 한컴오피스 문서, 수식과 중첩 표 전체 지원을 주장하지 않는다.

## 검증 계약

테스트를 먼저 실패시켜 기존 거부 경로를 확인한다. 구현 후 기존 HWP와 새 HWPX 테스트, 전체 pytest, Ruff, Docker 필수 명령을 실행한다. 변환 fixture는 같은 HWP CLI가 만든 파일이므로 독립 구현과의 상호 운용성 검증으로 표현하지 않는다.
