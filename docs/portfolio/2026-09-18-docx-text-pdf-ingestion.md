# DOCX와 텍스트 PDF 규정 수집 첫 단계 (2026-09-18)

## Before / 문제

사내 문서가 DOCX 편집본이나 텍스트 PDF 배포본으로 제공될 수 있지만 수집기는 Markdown·HWP·HWPX만 발견했다. `read_document`는 두 확장자 모두 거부했다. 같은 이름의 DOCX/PDF를 한 폴더에 넣으면 현재 문서 ID 규칙은 파일 경로를 기준으로 하므로 동일 규정을 두 번 색인할 위험도 있었다.

실제 DOCX·PDF fixture와 실패 테스트 8개를 먼저 만들었다. 구현 전 파일 탐색은 DOCX/PDF를 찾지 못했고, 리더는 두 형식에 `Unsupported document format`을 반환했다. 중복 방지 테스트도 구조 검증에 도달하지 못했다.

## Why / 분석과 선택

- [python-docx](https://python-docx.readthedocs.io/en/latest/api/document.html)는 DOCX 문단·표를 원래 순서대로 순회할 수 있다. 이를 통해 단순 표의 열 이름과 셀 값을 조문 안에 연결한다.
- [pypdf](https://pypdf.readthedocs.io/en/latest/user/extract-text.html)는 텍스트 PDF의 페이지 글자를 읽는다. PDF 자체는 제목·문단·표의 의미 계층을 보장하지 않으므로 기존 조·항 구조 검사에서 실패하면 색인을 중단한다. 스캔본은 OCR 범위로 남긴다.
- 두 형식을 기존 구조화 Markdown에 정규화하여 `read_document(path) -> str`, 조/항 청킹, Qdrant payload 계약을 유지한다.
- 같은 폴더·파일명 줄기의 `.docx`와 `.pdf`는 편집본과 배포본일 수 있다. 내용 유사도로 권위를 추측하지 않고 색인 전에 오류를 내 운영자가 하나를 고르게 한다.

## Solution / 구현

- `app/office_reader.py`는 DOCX 문단·단순 표와 텍스트 PDF를 추출한다. DOCX의 탐지 가능한 자동 번호·병합/중첩 표·본문 인라인 이미지는 구조가 손실되지 않도록 명시적으로 거부한다. 추출 가능한 글자가 없는 PDF는 OCR이 필요하다는 오류를 반환한다.
- `app/document_reader.py`는 DOCX/PDF도 기존 서식 정규화·조항 수 검사에 연결한다. HWP/HWPX 입력 사용법은 유지한다.
- `scripts/ingest_md.py`는 확장자를 대소문자와 무관하게 발견하고, DOCX/PDF 동일 줄기 쌍을 `--reset`의 컬렉션 삭제 전에 거부한다.
- `requirements.txt`에 `python-docx==1.2.0`, `pypdf==6.10.0`을 추가했다. README와 설계·테스트 fixture를 갱신했다.

## Verification / 검증

| 항목 | 관찰 결과 |
| --- | --- |
| 실패 재현 | DOCX/PDF 입력·탐색, 빈 PDF, DOCX 자동 번호·병합 표·이미지, 중복 DOCX/PDF의 새 테스트 8개가 구현 전 실패했다. |
| 합성 DOCX | 37,155바이트. `python-docx`로 다시 열어 제목, 편, 제1조, 단순 표, 제2조의 문단·표 순서를 확인했다. 번들 `render_docx.py`는 필요한 LibreOffice `soffice.exe`가 없어 시각 검증을 완료하지 못했다. |
| 합성 PDF | 28,161바이트, 1페이지. `pdftoppm -f 1 -l 1 -png -r 120`으로 렌더링해 한글·표·조항 배치를 시각 확인했다. `PYTHONUTF8=1`에서 pypdf의 조 제목·원문자 항 텍스트 추출을 확인했다. |
| 새 파서 경로 | 두 파일 모두 제1조·제2조 parent와 항 child를 생성한다. DOCX 단순 표에는 `구분: 연차`, `신청 기한: 3영업일 전` 관계가 들어갔다. 텍스트 없는 PDF는 OCR 안내와 함께 실패한다. |
| 중복·손실 방지 | 같은 줄기의 DOCX/PDF는 재색인 삭제 전에 실패한다. 테스트한 DOCX 자동 번호·병합 표·인라인 이미지도 손실을 숨기지 않고 실패한다. |
| 수집 경로 | 서로 다른 이름으로 둔 DOCX/PDF 2개를 테스트 대역 임베딩·Qdrant로 흘려 8개 청크와 4개 child 포인트, 파일별 출처 제목을 확인했다. 실제 Qdrant 연결은 아니다. |
| 기존 대형 HWP 회귀 | 같은 합성 단일 HWP에서 parent 8,000개, child 24,000개, 고유 ID 32,000개와 개발용 질문의 목표 조항·답 문구 1,000/1,000 매핑을 유지했다. DOCX/PDF 품질 증거는 아니다. |
| 자동화 | Windows Python 3.11, HWP CLI v0.17.0. `HWP_CLI_PATH`, `PYTHONUTF8=1`로 `python -m pytest -q`: **344 passed, 1 skipped** (최종 실행 9.60초). `ruff check .`, `ruff format --check .`, `git diff --check`, 변경 문서 링크 검사(누락 0건), `docker compose config --quiet` 통과. |
| Docker 런타임 | `docker compose up -d`, `docker compose run --rm rag-api pytest -v`, `curl http://localhost:6333`, `docker compose run --rm rag-api python -m app.healthcheck`를 시도했다. Docker Desktop Linux 엔진 named pipe가 없어 컨테이너와 Qdrant에 연결하지 못했다. 임시 `.env`는 검증 후 제거했다. |

## After / 관찰 결과

규정 문서의 DOCX와 텍스트 PDF가 기존 조·항 기반 색인 입력으로 들어갈 수 있게 됐다. DOCX 단순 표의 헤더·값 관계도 검색용 텍스트에 남는다. 자동화 통과 개수는 지원 경로의 검증이며 실제 사내 문서 정확도나 검색 품질 개선 지표가 아니다.

## 증거와 한계

- 설계: [설계 기록](../superpowers/specs/2026-09-18-docx-text-pdf-ingestion-design.md), [구현 계획](../superpowers/plans/2026-09-18-docx-text-pdf-ingestion-implementation.md), `tests/test_docx_pdf_documents.py`.
- 합성 DOCX SHA-256: `a5781a80fccceff7ba0fa2cd8ff77f9066869678eb06e5e841bbe8f40bd54664`. 합성 PDF SHA-256: `4715e5b9158512a98807cb3f856892aca39d9a38a487183724aca13e1c89fd40`.
- PDF fixture는 표를 화면에 포함하지만 이번 pypdf 경로는 표의 셀 관계를 복원하지 않는다. 실제 PDF의 다단 배치, 반복 머리말, 숨은 텍스트, 페이지 좌표 인용과 스캔 OCR도 검증하지 않았다.
- DOCX의 사용자 정의 번호·떠 있는 이미지와 각주를 완전 탐지하지 못할 수 있다. 동일 줄기 감지는 이름이 다른 중복본을 발견하지 못한다. 실제 사내 문서, Qdrant 대량 색인, 검색 Recall, Qwen 답변 품질과 운영 비용은 이번 단계에서 측정하지 않았다.
