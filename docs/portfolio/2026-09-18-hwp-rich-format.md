# HWP 서식 내용 보존 파싱 (2026-09-18)

## Before / 문제

사내 규정 RAG의 HWP 입력은 CLI가 출력한 Markdown에서 조·항 경계만 복원했다. 표·각주·이미지가 함께 든 합성 HWP를 기존 파서에 넣어 재현했다.

| 관찰 항목 | 기존 결과 |
| --- | --- |
| 제1조 표의 `구분: 교통비` 열·값 관계 | 없음. 원시 파이프 표만 남음 |
| 제3조의 각주 `2영업일 이내` | 제3조에 없음. 문서 끝 정의가 제4조에 붙음 |
| 제4조 이미지 내부 글자 | 없음. `![image]()`만 남음 |
| 제4조 이미지 캡션 | 일반 텍스트로 남지만 이미지와 명시적으로 연결되지 않음 |

재현 명령은 `hwp cat tests/fixtures/mixed_rich_policy.hwp --format markdown`이다. 실패는 `tests/test_hwp_rich_format.py`를 먼저 작성해 확인했다. 기존 HWP에서 조·항 수가 맞아도 답변 근거의 열 의미와 조항 귀속은 틀릴 수 있었다.

## Why / 분석과 선택

HWP CLI v0.17.0의 Markdown에는 기본 표·번호 목록·각주 참조가 나오지만, 각주 정의는 문서 끝에 배치되고 이미지 자산은 `cat` 출력에 포함되지 않는다. 병합 표는 HTML 표로 나온다. JSON IR 전체로 청킹 경로를 교체하는 방안도 검토했으나, 현재의 대규모 단일 HWP와 조·항 메타데이터 계약을 유지하면서 실제로 재현한 손실부터 고치기로 했다.

`read_document`의 반환 형식은 구조화 Markdown으로 유지했다. 이미지가 있으면 HWP CLI `convert --media-dir`로 로컬 자산을 추출하고 Tesseract `kor+eng`로 글자를 읽는다. 이미지 자산·OCR 실행에 실패하거나 참조 각주 정의가 없으면 조용히 색인하지 않고 오류를 낸다. OCR 결과가 비어도 캡션이나 설명이 있는 그림은 그 텍스트를 보존한다. 사용자가 지정한 이미지 범위는 내부 글자와 캡션이며, 그림이나 흐름도의 의미 해석은 범위 밖이다.

## Solution / 구현

1. 파이프 표는 헤더와 각 행의 열·값을 `[표 행 N]` 텍스트로 만들었다. HTML 표는 병합 열 범위를 표시하고 행 병합 값을 다음 행에 반복한다.
2. 자동 번호 목록의 순서와 번호를 유지한다. 각주 정의는 참조 표지가 있는 줄로 옮겨 해당 조항에 귀속시킨다.
3. 이미지 자산을 임시 디렉터리로 추출하고 OCR 글자·인접 캡션을 같은 조항에 넣는다. 본문 중간 이미지도 처리한다. 이미지 경로는 임시 디렉터리 안으로 제한한다.
4. Docker 이미지에 Tesseract 실행 파일과 한국어·영어 언어 데이터를 설치하도록 명시했다. 호스트 직접 실행에는 별도 Tesseract 설치가 필요하다.

## Verification / 검증

- 합성 실제 HWP `mixed_rich_policy.hwp`에서 표 열·값, 번호 목록, 각주 귀속, 이미지 자산·캡션·주입 OCR 결과를 확인했다. 병합 표 HWP `merged_table_policy.hwp`에서는 병합 범위와 각 셀을 확인했다. OCR 실행 명령과 한국어·영어 설정은 테스트 대역으로 확인했다.
- Python 3.11.4, HWP CLI 0.17.0, Windows 호스트에서 `HWP_CLI_PATH`와 `PYTHONUTF8=1`을 설정해 `python -m pytest -q`를 실행했다: **333 passed, 1 skipped** (최종 실행 7.15초). `ruff check .`, `ruff format --check .`, `git diff --check`도 통과했다.
- 이전 실험의 1,000개 정책 단일 HWP 300,544바이트를 같은 파서로 재검사했다. 8,000 parent, 24,000 child, 32,000 고유 ID를 얻었다. 개발용 생성 질문 1,000개의 목표 조항 ID와 기대 답 문구가 모두 해당 parent 텍스트에서 발견됐다. 이 검사는 검색·답변 품질 평가가 아니다.
- Docker 필수 명령을 실행했으나 최초에는 `.env`가 없어 실패했다. `.env.example`을 작업 트리의 무시 대상 `.env`로 복사해 재시도했고 Docker 엔진 파이프가 없어 컨테이너 실행, Qdrant 연결, healthcheck는 검증하지 못했다. Docker Desktop을 시작했지만 엔진 응답이 계속 멈췄고 `com.docker.service`는 현재 사용자 권한으로 시작할 수 없었다. 이미지 빌드와 컨테이너 내부 OCR은 미검증이다.
- [PR #16](https://github.com/bbungjun/onpremis_rag_chatbot/pull/16)의 GitHub Actions `lint`와 `test`가 통과했다. 구현 커밋은 `56b721f`다. CI 테스트는 Docker 이미지 빌드·실제 OCR 품질 검사를 포함하지 않는다.

## After / 측정 결과

동일한 합성 HWP에서 표의 열·값 관계가 제1조 청크에 나타났고, `2영업일 이내` 각주는 제3조에만 들어갔다. 이미지 내부 글자와 캡션은 제4조에 들어갔다. 번호 목록 1·2번 순서와 병합 표 셀도 보존됐다. 이미지 OCR 글자는 테스트 대역 값이므로 실제 OCR 정확도 개선으로 해석하지 않는다. 전체 RAG의 검색 Recall, 답변 정확도, 처리량, 지연시간은 이번 변경에서 측정하지 않았다.

## 증거 및 한계

- 합성 fixture SHA-256: `mixed_rich_policy.hwp` 24,576바이트, `79d312cea495c4d7f04df81c1a606b2bc1590607c4b518e13c031b355e1438ab`; `merged_table_policy.hwp` 12,288바이트, `29a738aa36629931ef559d20707f89b2b47d3e657dce7893f65cec06dc7471a9`.
- 대규모 단일 HWP SHA-256: `c21b51d7191ca7d58df5d7141b7da50f6bfab3a1d28a80301009da732ad0de0a`. 생성 질문은 개발용이며 독립 홀드아웃이 아니다.
- 모델·top-k·Qdrant 설정은 사용하지 않은 파싱 회귀 검사다. Docker 이미지 빌드와 실제 Tesseract OCR은 컨테이너 엔진이 준비되기 전까지 측정하지 않았다.
- 실제 사내 HWP의 복잡한 중첩 표, 수식, 스캔 문서, 페이지 좌표, 흐름도 의미, OCR 오인식률은 확인하지 않았다. 실제 문서를 받을 때 서식별 표본과 정답 텍스트를 고정하고 추출 정확도를 별도로 평가해야 한다.

설계와 재현 범위: [설계](../superpowers/specs/2026-09-18-hwp-rich-format-design.md), [구현 계획](../superpowers/plans/2026-09-18-hwp-rich-format-implementation.md), `tests/test_hwp_rich_format.py`.
