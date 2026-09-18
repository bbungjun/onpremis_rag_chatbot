# HWPX 입력과 파싱 학습 첫 단계 (2026-09-18)

## Before / 문제

HWP CLI v0.17.0은 HWPX를 읽을 수 있지만 제품의 `read_document`는 `.hwpx`에서 `Unsupported document format`을 반환했고, `discover_source_files`는 파일을 찾지 않았다. 실제 HWPX 합성 fixture를 준비한 뒤 `tests/test_hwpx_documents.py`의 두 테스트가 이 이유로 모두 실패했다.

사용자가 공유한 [HWP/HWPX 구조 설명](https://dbhyeong.github.io/blog/hwp-hwpx-format-parsing-python)은 HWP 바이너리와 HWPX ZIP/XML을 구분하는 데 유용하다. 그러나 `hp:t` 글자만 수집하면 자동 번호·표 열/값·각주 참조와 같은 RAG 근거 구조가 남지 않는지 직접 확인해야 했다.

## Why / 선택

기존 [HWP CLI](https://github.com/STAIxBWLB/hwp-cli)는 HWP/HWPX 모두를 Markdown 또는 JSON IR로 추출한다. 호출자에게 이미 제공하는 `read_document(path) -> str` interface를 유지하고 같은 adapter를 재사용하면 입력 범위를 늘리면서 표·각주·이미지 보강을 중복 구현하지 않는다. HWPX XML의 텍스트만 뽑는 경로는 학습용 비교 기준으로 사용하고 제품 파서로 채택하지 않았다. HWP 5.0 바이너리 레코드를 직접 구현하는 작업도 이번 범위가 아니다.

## Solution / 구현

- `app/document_reader.py`가 `.hwpx`를 `.hwp`와 같은 CLI 추출·서식 보강·조항 검증 흐름으로 받는다.
- `scripts/ingest_md.py`가 대소문자와 관계없이 `.hwpx`를 발견한다.
- 합성 `mixed_rich_policy.hwpx` fixture와 표·목록·각주 귀속·이미지 OCR 경로·캡션을 확인하는 통합 테스트를 추가했다.
- [학습 노트](../HWPX_PARSING_STUDY.md)에 ZIP 엔트리와 XML 텍스트 노드, HWP CLI 결과를 나란히 확인하는 실습을 기록했다. README에도 입력 범위를 표시했다.

## Verification / 검증

| 검증 | 조건과 결과 |
| --- | --- |
| 실패 재현 | 구현 전 파일 탐색은 `[]`, 문서 리더는 `.hwpx`에 `ValueError`를 반환했다. 새 테스트 2개가 모두 실패했다. |
| 실제 형식 fixture | 합성 HWP를 `hwp convert ... -o ...hwpx --strict`로 변환했다. HWPX는 11,947바이트이고 `hwp info`에서 HWPX (OWPML)로 식별됐다. |
| 추출 비교 | 같은 CLI가 HWP와 HWPX에서 추출한 Markdown은 334자로 동일했다(SHA-256 `0502247506a1ede3782eb97c9b42f15837b23535212f69cd8191dea8522fdb13`). HWPX의 이미지 `image1.png`도 4,356바이트로 추출됐다. |
| XML 텍스트만 추출 | `Contents/section0.xml`의 `hp:t`만 연결하면 231자였다. `1.` 목록 번호, `[^1]` 각주 참조, `구분: 교통비` 관계가 없었다. 이것은 이 fixture의 관찰이며 모든 HWPX의 손실량이 아니다. |
| 통합 파싱 | HWPX에서 parent 4개·child 4개, 제1조 표, 제2조 목록, 제3조 각주, 제4조 캡션과 주입한 OCR 텍스트를 확인했다. 실제 OCR 인식률은 측정하지 않았다. |
| 자동화 | Windows Python 3.11, HWP CLI v0.17.0, `HWP_CLI_PATH`와 `PYTHONUTF8=1` 설정. 관련 테스트 `31 passed`, 전체 `python -m pytest -q`: **335 passed, 1 skipped** (6.00초). `ruff check .`, `ruff format --check .`, `docker compose config --quiet`, 변경 문서 링크 검사(누락 0건) 통과. |
| PR CI | [GitHub Actions 실행 35340369503](https://github.com/bbungjun/onpremis_rag_chatbot/actions/runs/35340369503)에서 lint와 test가 통과했다(구현 커밋 `bd2dd25`). |
| Docker 런타임 | `docker compose up -d`, `docker compose run --rm rag-api pytest -v`, `curl http://localhost:6333`, `docker compose run --rm rag-api python -m app.healthcheck`를 시도했다. Docker Desktop Linux 엔진 named pipe가 없어 컨테이너와 Qdrant가 시작되지 않았다. 임시 `.env`는 `.env.example`에서 만들고 검증 후 제거했다. |

## After / 결과

동일한 합성 규정을 담은 `.hwpx`가 HWP와 같은 구조화 청크 경로를 통과한다. 제품에서 HWPX를 발견하고 표·번호·각주·이미지 내용을 해당 조로 귀속할 수 있게 됐다. 이는 지원 입력 범위와 fixture 정확성의 검증이지 실제 사내 HWPX 전체의 파싱 정확도나 RAG 답변 품질 측정은 아니다.

## 증거와 한계

- 설계: [HWPX 입력 설계](../superpowers/specs/2026-09-18-hwpx-input-design.md), [학습 노트](../HWPX_PARSING_STUDY.md), `tests/test_hwpx_documents.py`.
- 검토 PR: [#16](https://github.com/bbungjun/onpremis_rag_chatbot/pull/16).
- HWPX fixture SHA-256: `2eaa27cc4e2046165541432321655661618be56559168795b12a76c0e9af4120`. 원본 합성 HWP SHA-256: `79d312cea495c4d7f04df81c1a606b2bc1590607c4b518e13c031b355e1438ab`.
- 생성과 추출에 같은 HWP CLI를 사용했으므로 독립 한컴오피스 HWPX와의 상호 운용성은 확인하지 않았다. 암호화 문서, 수식, 중첩 표, 이미지 실제 OCR 정확도, Qdrant 검색·답변 지표는 미측정이다.
