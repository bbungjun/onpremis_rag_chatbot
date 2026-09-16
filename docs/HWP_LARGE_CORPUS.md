# 대규모 HWP 규정 코퍼스 실험

## 성격

이 생성기는 **가상회사 합성 규정**을 HWP 5.0 바이너리로 만든다. 실제 회사의 효력 있는 규정이 아니다. 10개 업무 주제, 20개 조직, 5개 고용 형태를 조합한 기본 1,000개 파일은 포맷 수집과 부하 시험용이다. 문구가 템플릿 기반이므로 이 데이터에서 높은 검색 점수가 나와도 실제 사내 문서에 대한 정확도 증거가 되지 않는다. 생성 질문은 개발용 회귀 검사이며 독립 홀드아웃이 아니다.

## 생성

HWP CLI v0.17.0을 설치하거나 `HWP_CLI_PATH`에 실행 파일 경로를 설정한다. [릴리스](https://github.com/STAIxBWLB/hwp-cli/releases/tag/v0.17.0)의 Windows/Linux 바이너리를 사용할 수 있다. Docker 이미지에는 Linux x86_64 바이너리를 SHA-256 검증과 함께 고정한다. 다른 CPU 아키텍처의 Docker 빌드는 별도 바이너리가 필요하다.

```powershell
python scripts/generate_hwp_corpus.py --count 1000 --output reports/hwp-large-corpus/run-1000
```

`docs/`에 HWP 파일, `source_md/`에 생성 입력, `manifest.jsonl`에 해시·크기·청크 수, `qa_generated_dev.jsonl`에 생성 질문을 기록한다. 출력은 Git에서 제외한다. 생성기는 각 파일을 HWP로 기록한 후 포맷 검증, 텍스트 재추출, 8개 조·24개 항 보존을 확인한다.

## 색인

Docker 이미지의 `hwp` 실행 파일은 `scripts/ingest_md.py`에서 사용한다. 로컬 셸에서 실행할 때는 `HWP_CLI_PATH`를 설정한다. 예:

```powershell
$env:HWP_CLI_PATH = "C:\path\to\hwp.exe"
python scripts/ingest_md.py reports/hwp-large-corpus/run-1000/docs --batch-size 128 --reset
```

`--reset`은 설정된 Qdrant 컬렉션을 삭제하고 다시 만든다. 기존 색인을 보존하려면 빼고 실행한다. 생성 문서와 기존 규정집을 함께 평가할 때는 테스트용 컬렉션을 지정해야 한다. HWP 추출에 조/항이 없으면 색인을 중단한다.

Docker에서 색인하려면 생성한 `docs/`를 컨테이너에 읽기 전용으로 마운트하고 동일한 스크립트를 실행한다. `reports/`는 이미지 빌드 문맥에서 제외된다.

## 검증 지표

- 수집: 파일 수, 총 바이트, 조/항 수, 실패 수, 전체 소요 시간, 최고 RAM, Qdrant 저장 공간.
- 검색: 동일 질문 세트에서 Recall@k, MRR, 무답 처리, 출처 정확도, p50/p95 지연시간.
- HWP 추출: 표·자동 번호·각주·이미지 텍스트가 있는 별도 파일로 비교한다. 현 합성 코퍼스는 텍스트 중심이다.

서로 다른 규모를 비교할 때는 모델, 하드웨어, top-k, 검색 설정, 질문 세트를 고정한다. 대량 색인 및 검색 지표는 실제로 측정한 뒤 포트폴리오 문서에 기록한다.
