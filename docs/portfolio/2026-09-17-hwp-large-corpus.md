# HWP 대규모 규정 코퍼스와 수집 경로 (2026-09-17)

## Before / 문제

기존 실험은 합성 Markdown 규정집 1개, 207,536바이트, 100개 조, 검색용 child 600개에 머물렀다. `scripts/ingest_md.py`는 `.md`만 발견했고, 전체 포인트를 메모리에 쌓아 한 번에 업로드했다. `app/rag_pipeline.py`의 parent 중복 제거는 `parent_id`만 사용했다. 여러 문서가 모두 `제1조`를 가질 때 한 문서의 근거가 누락되는 실패 테스트가 재현됐다. HWP 원본은 현재 수집 경로에 들어갈 수 없었다.

## Why / 분석과 선택

대규모 회사 문서의 입력 형식과 조/항 구조, 문서별 출처가 함께 증가한다. DB를 바꾸기 전에 포맷 읽기, 적재 메모리, 다중 문서 식별을 해결해야 한다. HWP 5.0 바이너리를 텍스트로 잘못 읽는 대신 Apache-2.0 `hwp-cli` v0.17.0을 고정해 생성과 추출에 사용했다. 추출된 제목 자동 번호를 구조화 Markdown으로 정규화하여 기존 청커와 검색 흐름을 재사용했다. `pyhwp`의 실험적 텍스트 변환과 오래된 공개 Python 지원 범위를 고려해 이번 경로에는 채택하지 않았다.

합성 문서는 10개 업무 주제 × 20개 조직 × 5개 고용 형태 조합으로 만들었다. 템플릿 기반 파일 1,000개를 실제 회사 규정처럼 주장하지 않는다. 생성 질문도 독립 홀드아웃이 아닌 개발용 회귀 질문이다.

## Solution / 구현

- `app/document_reader.py`: HWP CLI를 인자 배열로 호출하고, 자동 제목 번호를 제거하며, 조/항을 찾지 못하면 실패한다.
- `scripts/ingest_md.py`: Markdown/HWP를 발견하고 128개 기본 배치로 업로드한다. 빈 입력과 조/항이 없는 문서를 거부하며 `--reset` 이전에 모든 입력의 구조를 확인한다.
- `app/rag_pipeline.py`: `(document_id, parent_id)`로 중복을 제거해 서로 다른 문서의 같은 조 번호를 보존한다.
- `scripts/generate_hwp_corpus.py`: HWP 바이너리 생성, 포맷 검증, 텍스트 재추출, 조/항 수와 핵심 문구의 왕복 확인, manifest와 개발 질문 작성.
- Docker 이미지에 HWP CLI Linux x86_64 릴리스 바이너리를 SHA-256으로 고정했다. 생성 원본과 대량 실험 파일은 Git에서 제외했다.

첫 생성 시 Markdown 문단 사이에 빈 줄이 없자 HWP 변환 결과가 조 제목과 항을 한 문단으로 합쳤다. 생성기를 빈 문단으로 분리해 HWP 재추출에서 조·항 경계가 보존되도록 했다.

## Verification / 검증

| 검증 | 조건과 결과 |
| --- | --- |
| 실패 재현 | 새 HWP 입력, 배치, 문서별 parent 테스트 5개가 구현 전 실패했다. 특히 다른 문서의 `제1조`가 하나로 합쳐졌다. |
| Python 테스트 | Windows Python 3.11, `PYTHONUTF8=1`, `HWP_CLI_PATH`를 로컬 hwp.exe로 지정하고 `python -m pytest -q`: **320 passed, 1 skipped** (6.49초). |
| HWP 생성 | `python scripts/generate_hwp_corpus.py --count 1000 --output reports/hwp-large-corpus/run-1000 --hwp-cli <검증된 hwp.exe>` 성공. 파일마다 `hwp validate`, `hwp cat`, 8개 조/24개 child 및 핵심 문구 보존을 검사했다. |
| 샘플 육안 검사 | 첫 HWP를 PNG 첫 페이지로 렌더링해 제목, 조, 항의 순서와 한글 본문을 확인했다. 렌더러가 글꼴을 대체했으므로 원본 한컴 화면과의 픽셀 동일성은 평가하지 않았다. |
| 압축 산출물 | `output/hwp-large-corpus-1000.zip`: 2,002개 항목, `zipfile.testzip()` 오류 없음. |
| Compose 정적 검사 | `docker compose config --quiet` 성공. |
| Docker 런타임 | `docker compose up -d`, `docker compose run --rm rag-api pytest -v`, `curl.exe --max-time 5 http://localhost:6333`, `docker compose run --rm rag-api python -m app.healthcheck`를 시도했다. Docker Desktop Linux 엔진 named pipe가 없어 컨테이너가 시작되지 않았고 Qdrant 접속도 실패했다. 서비스 시작은 권한 부족으로 실패했다. |

## After / 관찰 결과

| 지표 | Before | After | 해석 |
| --- | ---: | ---: | --- |
| 생성된 원본 파일 | Markdown 1개 | HWP 1,000개 | 파일 형식과 데이터셋이 달라 품질 개선 비교가 아님 |
| 원본 바이트 | 207,536 | 36,816,384 | HWP 바이너리 총합, Qdrant 디스크 사용량이 아님 |
| 구조화 parent | 100 | 8,000 | 생성·재추출 검사 결과 |
| 검색용 child | 600 | 24,000 | 40배의 색인 예정 청크. 실제 Qdrant 적재 수는 미측정 |
| HWP 파일 해시 고유 수 | 해당 없음 | 1,000/1,000 | 파일 중복 방지 확인; 의미 다양성 지표는 아님 |

검색 Recall, MRR, 출처 정확도, Qwen 답변 품질, 색인 시간, 검색 p95, Qdrant RAM/디스크는 **측정하지 않음**. Docker 엔진에 연결되지 않아 대규모 런타임 색인과 질의를 실행할 수 없었다. pytest 통과는 코드 검증이지 사용자 가치 지표가 아니다.

## 증거와 한계

- 설계: `docs/superpowers/specs/2026-09-17-hwp-large-corpus-design.md`; 구현 계획: `docs/superpowers/plans/2026-09-17-hwp-large-corpus-implementation.md`.
- 구현 커밋: [`3d9332d`](https://github.com/bbungjun/onpremis_rag_chatbot/commit/3d9332d); 검토 PR: [#14](https://github.com/bbungjun/onpremis_rag_chatbot/pull/14).
- 로컬 원시 산출물: `reports/hwp-large-corpus/run-1000/manifest.jsonl`, `qa_generated_dev.jsonl`, `docs/`, `source_md/`. Git에는 포함하지 않는다.
- manifest SHA-256: `79207ad31672b0fc33880a154d9ba1130bd8c9dcb7e7a4cb5a3403a195ee19d4`.
- 압축 산출물: `output/hwp-large-corpus-1000.zip`, 31,092,905바이트, SHA-256 `98a31e7222495222a82cbde8bde7d7569529d670d92992dc3df1c2660ff44e5f`.
- 실험 예시 설정인 `.env.example`에는 `bge-m3`, Qwen `qwen3:4b-instruct`, parent top-k 5가 기재되어 있다. 이번 대량 코퍼스에는 두 모델을 실행하지 않았다.
- 생성/추출 도구: `hwp-cli` v0.17.0. Windows 배포 ZIP SHA-256 `70f5a17789182566e328a9cdf6d3ec202722589b0a10d1c6a96825ba58a23e22`; Docker Linux x86_64 배포 TAR SHA-256 `842c05600b70cb04639958269426e5ffe83ef390a069df7936286c6081ac0f1b`.
- 생성 호스트: Windows, Intel Core i5-13600KF, 물리 RAM 31.8 GiB. 실행 날짜 2026-09-17 (Asia/Seoul).
- 같은 도구가 HWP를 쓰고 읽었으므로 외부 구현과의 상호 운용성은 미검증이다. 템플릿 문서에는 실제 회사 문서의 표, 그림, 각주, 서명, 암호화와 문서 버전 충돌이 반영되지 않았다. `--reset` 전 구조 검사는 성공해도 이후 임베딩·업로드 실패 시 기존 컬렉션을 자동 복구하지 못한다. 테스트용 컬렉션에서 먼저 실행하고, 런타임 사용 전 대표 HWP 샘플과 독립 사람이 만든 질문 세트로 후속 평가가 필요하다.
