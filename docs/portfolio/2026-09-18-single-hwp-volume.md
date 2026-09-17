# 단일 HWP 규정집 실험 (2026-09-18)

## Before / 문제

2026-09-17 실험은 합성 정책 1,000개를 HWP 파일 1,000개(총 36,816,384바이트)에 나눠 담았다. 검색용 항 24,000개를 만들었지만, 사용자가 의도한 한 권의 규정집 입력은 재현하지 못했다. 기존 청커에 `제1조`가 두 번 들어 있는 책을 주면 `jo-1` parent와 `jo-1-hang-1` child ID가 중복되는 실패를 확인했다. 수집기의 parent 텍스트 매핑과 Qdrant UUID가 이 ID를 사용하므로 실제 색인에서는 한 조의 내용이 다른 조로 대체될 수 있었다.

## Why / 판단

Qdrant는 원본 HWP 파일을 검색 단위로 저장하지 않고 child 벡터 포인트를 저장한다. 따라서 정책 1,000개를 한 파일에 합쳐도 검색용 청크 24,000개라는 문제 규모는 유지된다. 단일 파일은 규정집 배포와 출처 관리에 맞지만, 조항 하나가 바뀌면 HWP 파일 전체가 변경된 것으로 취급된다. 현재 수집 경로는 부분 문서 변경 감지를 하지 않으므로 전체 재색인이 필요하다.

한 권을 편(주제)·장(조직)·절(고용 형태)로 구성하고 조 번호를 책 전체에서 1~8,000으로 매겼다. 청커에도 반복 조·항 번호에 occurrence 접미사를 부여하는 방어를 추가해, 이후 실제 문서가 부분별로 조 번호를 다시 시작해도 ID가 겹치지 않게 했다. 기존 정책별 HWP 생성은 `--layout split`로 남겼다.

## Solution / 변경

- `scripts/generate_hwp_corpus.py`의 기본 레이아웃을 `book`으로 지정했다. 정책 1,000개를 단일 HWP에 넣고 개발 질문 1,000개를 전역 조 번호에 연결한다.
- `app/chunking.py`의 동일 조 번호 반복 시 parent/child ID 충돌을 막았다. 첫 등장 ID는 기존 호환성을 위해 유지한다.
- HWP 한 권과 생성 원본 Markdown을 별도 디렉터리에 두어 `docs/`만 색인하면 원본 Markdown이 중복 색인되지 않게 했다.
- README, HWP 사용 안내와 설계/계획 문서를 단일 규정집 기준으로 갱신했다.

## Verification / 검증

| 항목 | 조건과 결과 |
| --- | --- |
| 실패 재현 | 동일 파일에 두 개의 `제1조`를 넣으면 기존 청커가 parent/child ID를 중복 생성했다. 수정 후 두 parent와 두 child의 ID가 모두 고유했다. |
| 작은 실제 HWP | 2개 정책을 한 HWP로 생성·재추출하여 16개 조, 48개 항과 마지막 `제16조`를 확인했다. |
| 전체 Python 테스트 | Windows Python 3.11, `PYTHONUTF8=1`, `HWP_CLI_PATH` 설정, `python -m pytest -q`: **324 passed, 1 skipped** (6.24초). |
| 단일 HWP 생성 | `python scripts/generate_hwp_corpus.py --layout book --count 1000 --output reports/hwp-large-corpus/book-1000 --hwp-cli <hwp.exe>` 성공. HWP CLI 유효성 검사와 재추출 후 10개 편, 200개 장, 1,000개 절, 8,000개 조, 24,000개 항, 32,000개 고유 청크 ID를 확인했다. |
| 생성 질문 매핑 | 개발 질문 1,000개가 서로 다른 대상 조를 가리키고, 모든 기대 답변 문구가 해당 조에 있었다(1,000/1,000). 이는 독립 검색 평가가 아니다. |
| 육안 검사 | HWP 첫 페이지 PNG에 편/장/절/조/항과 한글 본문이 표시되는 것을 확인했다. 렌더러의 글꼴 대체가 발생하여 한컴오피스 화면과의 동일성은 평가하지 않았다. |
| Compose 정적 검사 | `docker compose config --quiet` 성공. |
| Docker 런타임 | `docker compose up -d`, `docker compose run --rm rag-api pytest -v`, `curl.exe --max-time 5 http://localhost:6333`, `docker compose run --rm rag-api python -m app.healthcheck`를 시도했다. Docker Desktop Linux 엔진 named pipe가 없어 실패했다. 실제 Qdrant 색인/검색은 미실행이다. |

## After / 관찰 결과

| 지표 | 분리형 HWP | 단일 HWP | 해석 |
| --- | ---: | ---: | --- |
| HWP 파일 | 1,000개 | 1개 | 같은 합성 정책 1,000개를 다른 구조로 배치 |
| HWP 바이트 합계 | 36,816,384 | 300,544 | 반복 문구의 압축과 파일별 오버헤드가 크게 작용한 합성 데이터 결과. 실제 규정집에 일반화할 수 없음 |
| 구조화 조 | 8,000 | 8,000 | HWP 재추출 기준 |
| 검색용 항 | 24,000 | 24,000 | 실제 Qdrant 벡터 포인트 수는 미측정 |
| 개발 질문 | 1,000 | 1,000 | 생성 규칙에서 나온 질문이며 홀드아웃 아님 |

단일 HWP 추출 텍스트는 1,002,915자였다. 원본 Markdown은 2,263,783바이트다. `read_document` 1회 호출 시간은 0.288초였지만 캐시와 단일 실행의 영향을 분리하지 않았으므로 속도 개선으로 해석하지 않는다. 검색 Recall, MRR, Qwen 답변 품질, Qdrant 디스크/RAM, 전체 색인 시간과 검색 지연은 **측정하지 않음**.

## 증거와 한계

- 설계: `docs/superpowers/specs/2026-09-18-single-hwp-volume-design.md`; 계획: `docs/superpowers/plans/2026-09-18-single-hwp-volume-implementation.md`.
- 로컬 원시 결과: `reports/hwp-large-corpus/book-1000/docs/synthetic-regulations-1000.hwp`, `source_md/`, `manifest.jsonl`, `qa_generated_dev.jsonl`. 생성 결과는 Git에 포함하지 않는다.
- HWP SHA-256: `c21b51d7191ca7d58df5d7141b7da50f6bfab3a1d28a80301009da732ad0de0a`; manifest SHA-256: `550b457236ba0c62edf9b48bb5b59d015be68cf2b7083a6f9a66cce300498644`; 원본 Markdown SHA-256: `12ef5904d881632e0d27fcaf959302c54437448ed9af014ee814d7c72853552b`.
- 도구/환경: `hwp-cli` v0.17.0, Windows, Python 3.11, Intel Core i5-13600KF, RAM 31.8 GiB, 2026-09-18 (Asia/Seoul). 모델은 실행하지 않았다.
- 같은 HWP CLI가 쓰고 읽었으므로 독립 구현과의 상호 운용성은 미검증이다. 한컴오피스에서 전체 1,000개 정책을 열어보지 못했다. 합성 템플릿은 표, 이미지, 각주, 첨부, 실제 개정 이력과 부서 권한을 반영하지 않는다. 실제 운영 전 대표 문서와 사람 작성 질문으로 별도 검증이 필요하다.
