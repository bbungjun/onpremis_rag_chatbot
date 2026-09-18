# 합성 사내규정집 DOCX·PDF 두 버전 (2026-09-19)

## Before / 문제

정책 1,000개를 묶은 합성 규정집은 HWP 한 권만 있었다. DOCX와 텍스트 PDF 수집 경로를 검증할 같은 규모의 두 버전이 없어, 형식 차이와 문서 내용 차이를 분리하기 어려웠다. 별도로 작성한 두 규정집을 비교하면 조항이나 숫자가 다른 채로 색인될 수도 있었다.

## Why / 분석과 선택

`make_regulation_book(1000)`의 구조화 Markdown을 두 파일의 유일한 내용 원본으로 삼았다. 이전 HWP 생성 원본은 Windows CRLF로 저장돼 바이트 SHA가 다르지만, 줄바꿈을 정규화하면 현재 생성 함수의 내용과 완전히 같았다. 이전 원본은 2,263,783바이트(SHA-256 `12ef5904d881632e0d27fcaf959302c54437448ed9af014ee814d7c72853552b`), LF UTF-8 논리 원문은 2,197,364바이트(SHA-256 `0e7ff46082dc68eb10790e9b619c48d207e95fc381a977543d7977698ebc6510`)다.

DOCX는 편/장/절/조를 제목 스타일로, PDF는 선택 가능한 한글 텍스트로 배치했다. 두 파일의 바이너리 크기나 페이지 수가 같을 필요는 없지만, **조·항 ID와 검색용 항 전체의 문구**는 같아야 한다. 같은 규정의 DOCX/PDF를 동시에 색인하면 중복이므로 비교용 산출물로 두고 실제 색인에는 한 형식만 선택한다.

## Solution / 구현

- `scripts/generate_regulation_book_formats.py`가 `--count`, `--output`, 선택적 `--font-path`를 받아 DOCX 1개와 PDF 1개를 만든다. PDF에는 선택한 TrueType 한글 글꼴을 임베딩한다.
- 생성기는 결과를 다시 `read_document`로 읽어 원문과 모든 child ID·문구, parent ID, 생성 개발 질문의 목표 조·답 문구를 비교한다. 기존 출력 파일을 덮어쓰지 않는다.
- DOCX 제목 스타일과 PDF 페이지 레이아웃에 같은 원문을 배치하고 manifest에 파일별 바이트·SHA-256·원문 해시·PDF 페이지 수를 기록한다.
- 작은 2정책 왕복 테스트와 README/아키텍처 설명을 추가했다. 생성 DOCX/PDF는 Git에서 제외한 `output/`에 보관한다.

## Verification / 검증

| 항목 | 조건과 결과 |
| --- | --- |
| 실패 재현 | 생성기 추가 전 2정책 왕복 테스트 2개가 모듈 부재로 실패했다. 구현 후 2개 모두 통과했다. |
| 1,000정책 생성 | 같은 원문에서 DOCX/PDF 각 1개를 생성했다. 양쪽 모두 parent 8,000개, child 24,000개, 고유 ID 32,000개와 전 child 텍스트 일치, 생성 개발 질문 대상 조·답 문구 1,000/1,000을 검증했다. 독립 검색 평가가 아니다. |
| 기존 HWP와 직접 비교 | 기존 단일 HWP와 새 DOCX/PDF를 각각 `read_document`로 읽어 child ID별 공백 정규화 본문 24,000개를 비교했다. DOCX와 PDF 모두 HWP 대비 불일치 **0건**이었다. |
| DOCX 구조 | 재오픈 시 문단 33,212개: Title 1, Normal 24,001, Heading 1 10, Heading 2 200, Heading 3 1,000, Heading 4 8,000. 마지막 항 본문까지 읽혔다. |
| PDF 텍스트·형식 | `pdfinfo`: A4, 890페이지. 전체 페이지 텍스트를 pypdf로 읽어 원문의 모든 항을 비교했다. |
| PDF 이미지 검증 | `pdftoppm -png -r 72`로 890페이지 전부 렌더했다. 모든 PNG가 596×842px이고 빈 페이지 0, 가장자리 8px 이내 내용 0이다. 첫·중간(445)·마지막(890) 페이지를 144DPI로 다시 렌더해 한글 글자, 조항 흐름과 페이지 여백을 눈으로 확인했다. 모든 890페이지를 100% 확대해 수동 검토하지는 않았다. |
| DOCX 시각 검증 | 번들 `render_docx.py --emit_pdf` 실행은 `soffice.exe`가 번들 PATH에 없어 실패했다. 구조·전체 텍스트 왕복은 검증했지만 페이지 레이아웃은 육안 검증하지 못했다. |
| 자동화 | Windows Python 3.11, HWP CLI v0.17.0 설정 후 `python -m pytest -q`: **346 passed, 1 skipped** (최종 실행 7.53초). `ruff check .`, `ruff format --check .`, `git diff --check`, `docker compose config --quiet` 통과. pytest 건수는 사용자 가치 지표가 아니다. |
| PR CI | [GitHub Actions 실행 35392033331](https://github.com/bbungjun/onpremis_rag_chatbot/actions/runs/35392033331)에서 lint와 test가 통과했다(구현 커밋 `63aa6d8`). |
| Docker 런타임 | `docker compose up -d`, `docker compose run --rm rag-api pytest -v`, `curl http://localhost:6333`, `docker compose run --rm rag-api python -m app.healthcheck`를 시도했다. Docker Desktop Linux 엔진 named pipe가 없어 컨테이너와 Qdrant가 시작되지 않았다. 임시 `.env`는 검증 후 제거했다. |

## After / 관찰 결과

HWP와 논리적으로 같은 1,000개 정책의 DOCX·PDF 각 한 권을 만들었다. 두 형식 모두 제1조부터 제8,000조, 24,000개 항의 텍스트와 개발 질문 매핑을 보존했다. 이는 **파일 생성·추출 계약의 검증**이다. 같은 조건에서 Qdrant 실제 적재·검색 지연, RAG 답변 품질, 운영 저장 공간 또는 인덱스 RAM은 측정하지 않았다.

## 증거와 한계

- [설계](../superpowers/specs/2026-09-19-docx-pdf-regulation-book-design.md), [구현 계획](../superpowers/plans/2026-09-19-docx-pdf-regulation-book-implementation.md), `tests/test_generate_regulation_book_formats.py`.
- 검토 PR: [#19](https://github.com/bbungjun/onpremis_rag_chatbot/pull/19).
- 로컬 생성 결과: `output/docx-pdf-regulation-book-1000-20260919/synthetic-regulations-1000.docx` 113,090바이트, SHA-256 `e8c3da8761e654c3c6fddfd75f6460285a0c5ac8874e88f971d7ed3a99b6195b`; `synthetic-regulations-1000.pdf` 1,729,794바이트, SHA-256 `011eec07caee21246e06616ebbc10bd859092b306c45721cad690aa995905472`.
- `manifest.json` SHA-256 `5562d5b7ed59e9b65b947b9ce08e2f8bd8d7a44406ca96ba724e6133c44abce8`. 생성 조건: 2026-09-19, Windows, Intel Core i5-13600KF(14코어/20스레드), 물리 RAM 31.84GiB, `python-docx` 1.2.0, `reportlab` 4.4.9, `pypdf` 6.10.0, PDF 글꼴 `malgun.ttf`. 모델과 검색 top-k는 실행하지 않았다.
- 작은 테스트의 기본 PDF 글꼴은 CID 대체 글꼴이라 최종 Malgun PDF의 픽셀과 같지 않다. 합성 템플릿에는 실제 회사 문서의 표·도형·개정 이력·부서 권한과 스캔 이미지가 없다. DOCX 전 페이지의 렌더링, 실제 사내 문서와의 상호 운용성, 대형 코퍼스 색인·검색은 미측정이다.
- PDF 전 페이지 검증 PNG 890개(103,532,871바이트)는 무시 대상 작업 트리의 `tmp/render_pdf/`에 남았다. 안전 경로 확인 후 정리를 시도했지만 자동 승인 검토가 파일 삭제 명령을 `blocked by policy`로 거절했다. 최종 DOCX/PDF 산출물은 별도의 `output/`에 있다.
