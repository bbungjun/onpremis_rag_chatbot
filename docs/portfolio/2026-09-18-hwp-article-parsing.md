# HWP 조·항 경계 파싱 보강 (2026-09-18)

## Before / 문제

이전 HWP 파서는 추출된 Markdown에서 조 제목이 한 줄 전체와 정확히 일치할 때만 청킹했다. HWP CLI가 `**제1조 (연차)** ① ... ② ...`를 한 문단으로 내보내면 색인이 실패했고, `**제5조의2 (예외)**`는 조로 인식되지 않았다. 두 조가 한 문단으로 합쳐지면 두 번째 조가 첫 조의 본문에 흡수되는데도 parent/child가 하나씩 존재한다는 이유로 성공으로 반환됐다. 이 사례를 합성 HWP 파일과 실패 테스트로 재현했다. 조 번호의 가지 번호를 직접 지정할 API 필터도 없었다.

## Why / 판단

조·항 경계를 잃으면 Qdrant에 들어가는 검색 포인트와 parent 텍스트가 달라지고, 답변 출처의 조 번호도 틀릴 수 있다. [Qdrant는 같은 ID를 업서트하면 기존 포인트를 덮어쓰므로](https://qdrant.tech/documentation/manage-data/points/) 구별되는 조는 구별되는 ID를 가져야 한다. 외부 HWP 변환기의 문단 결합을 허용하되, 조 제목 후보 수와 파싱 결과가 다르면 명시적으로 실패하도록 했다. 실제 사내 HWP의 서식 다양성은 아직 확보되지 않아 지원 범위를 텍스트 경계에 한정했다.

## Solution / 구현

- `app/document_reader.py`: 한 문단의 여러 굵은 조 제목을 분리하고, 조 제목 뒤에 이어진 원문자 항 표지를 별도 줄로 복원한다. 추출 원문의 조 제목 표지 수와 parent 청크 수가 다르면 색인을 중단한다.
- `app/chunking.py`: `제N조의M`을 파싱해 `jo_sub_no=M`, 별도 parent ID와 조 경로를 만든다. 일반 `제N조` ID는 유지한다.
- `app/server.py`: `jo_sub_no`를 API 편의 메타데이터 필터에 추가했다.
- 작은 실제 HWP fixture에서 줄바꿈이 합쳐진 조·항과 한 줄의 여러 조를 검증했다.

## Verification / 검증

| 구분 | 조건과 결과 |
| --- | --- |
| 실패 재현 | 구현 전 `제N조의M` 누락, 한 줄 조·항 파싱 실패, 부분 조 누락 무감지, 한 문단의 두 조 누락, API 가지 조 번호 필터 누락을 테스트로 확인했다. |
| 자동화 | Windows Python 3.11, `PYTHONUTF8=1`, `HWP_CLI_PATH` 설정 후 `python -m pytest -q`: **321 passed, 1 skipped** (6.61초). 기준선(최신 main 병합 직후)은 314 passed, 1 skipped였다. 테스트 증가분은 검증 범위이지 품질 지표가 아니다. |
| 큰 합성 HWP | `reports/hwp-large-corpus/book-1000/docs/synthetic-regulations-1000.hwp`를 다시 읽어 8,000개 parent, 24,000개 child, 32,000개 고유 청크 ID를 확인했다. 생성 개발 질문 1,000개의 대상 조에 기대 답변 문구가 모두 있었다. |
| 정적 검사 | `ruff check --output-format=github .`, `ruff format --check .`, `docker compose config --quiet`, `git diff --check` 통과. |
| PR CI | [GitHub Actions 실행 35260029023](https://github.com/bbungjun/onpremis_rag_chatbot/actions/runs/35260029023)에서 lint와 test가 모두 통과했다(커밋 `c697c26`). |
| Docker 런타임 | `docker compose up -d`, `docker compose run --rm rag-api pytest -v`, `curl.exe --max-time 5 http://localhost:6333`, `docker compose run --rm rag-api python -m app.healthcheck`를 시도했다. Docker Desktop Linux 엔진 named pipe가 없어 컨테이너와 Qdrant가 실행되지 않았다. |

## After / 관찰 결과

두 조가 한 HWP 문단에 합쳐진 재현 파일에서 이제 두 parent와 각각의 child가 만들어진다. `제5조의2`는 `jo-5-sub-2`로 분리되며 API에서 `jo_no=5`, `jo_sub_no=2`를 필터로 지정할 수 있다. 기존 1,000개 정책 합성 HWP의 조·항 수와 생성 질문 매핑은 유지됐다. 큰 HWP의 SHA-256은 이전과 동일한 `c21b51d7191ca7d58df5d7141b7da50f6bfab3a1d28a80301009da732ad0de0a`다.

실제 Qdrant 적재, 검색 Recall/MRR, 답변 근거성, 색인 시간·RAM·지연시간은 **측정하지 않음**. 파싱 정확도 개선은 재현 사례와 합성 문서 구조 범위에서만 주장한다.

## 증거와 한계

- 설계: `docs/superpowers/specs/2026-09-18-hwp-article-parsing-design.md`; 계획: `docs/superpowers/plans/2026-09-18-hwp-article-parsing-implementation.md`.
- 구현 커밋: [`a51fcb1`](https://github.com/bbungjun/onpremis_rag_chatbot/commit/a51fcb1); 검토 PR: [#14](https://github.com/bbungjun/onpremis_rag_chatbot/pull/14).
- fixture: `tests/fixtures/collapsed_article.hwp`(11,264바이트, SHA-256 `59622f728ec62225795f42ba601d0198f8aa3b6f1b5ef04c954b4dd6850c2c19`), `tests/fixtures/softbreak_multiple_articles.hwp`(11,264바이트, SHA-256 `a07494ca7f3a174117c54f4f714bc518f2a8e15d68716706e1cbd666e826252e`). HWP CLI v0.17.0으로 생성했다.
- 생성 문서와 fixture 모두 같은 CLI로 작성·추출했다. 독립 HWP 구현 및 실제 회사 문서와의 상호 운용성은 미검증이다. 굵은 조 제목이 일반 본문에서 인용되거나, 조 제목이 서식만으로 표현되고 텍스트 표지가 없는 경우에는 잘못 분리하거나 누락할 수 있다. 표·각주·이미지 OCR·페이지 좌표는 이번 범위 밖이다.
- 호스트: Windows, Intel Core i5-13600KF, RAM 31.8 GiB. 실행 날짜 2026-09-18 (Asia/Seoul). 모델과 검색 top-k는 이 파싱 검증에서 실행하지 않았다.
