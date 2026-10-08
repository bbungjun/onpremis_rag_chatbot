# 사용자별 문서 접근권한 현황 조사

2026-10-08 현재 작업 트리와 로컬 실행 상태 기준, **사용자·팀·역할별 문서 권한제어는 미구현**이다.
부서 및 보안등급 검색 필터는 있지만 검증된 사용자 신원으로 강제하는 권한 정책이 아니다.
이번 작업은 조사와 문서화이며 인증·권한 기능을 추가하지 않았다.

## Before / 질문

사내 규정 챗봇이 사용자의 접근권한 밖 문서를 답변하는지 확인하려면, 먼저 인증과 문서 권한
경계가 존재하는지 확인해야 한다. 앞선 모델 비교의 표식 출력률은 이러한 문서 권한 검증이 아니다.
사용자가 요청한 문자열을 출력한 것만으로 접근권한 우회나 실제 공격 성공을 입증할 수 없다.

## Why / 코드와 실행 경로

| 경계 | 확인 내용 |
| --- | --- |
| 사용자 인증 | app/server.py의 질의 라우트에 인증 dependency가 없고 미들웨어는 CORS뿐이다. 현재 미추적 app/onprem_server.py에도 인증 dependency/미들웨어가 없다. |
| 검색 필터 | department/security_level/metadata_filter는 요청 본문에서 받는다. 서버가 사용자 소속과 대조하지 않는다. |
| 필터 생략 | app/vector_store.py의 _build_filter는 None 또는 빈 필터에 None을 반환한다. 권한별 제한 없이 해당 collection을 검색하는 경로다. |
| parent 확장 | 검색된 child payload의 parent_text를 확장한다. 별도 사용자 신원이나 ACL 인자가 없고 권한 재검증도 없다. |
| 답변 출처 | 검색 parent에서 source_path/chunk_id/score를 반환한다. 사용자별 공개 가능 여부를 검사하지 않는다. |
| 프록시 | 현재 deploy/Caddyfile은 내부 TLS와 Streamlit reverse proxy이며 사용자 인증 설정이 없다. |
| 데이터 | 현재 llmenhance_chunks의 600 points 모두 department/security_level/acl/allowed_users/allowed_groups/user_id/tenant_id/owner 필드가 없었다. |

주요 근거 위치:

- app/server.py:55-80, 119-129, 269-280
- app/onprem_server.py:60-85, 116-136 (원래 작업 트리의 미추적 시연 코드)
- app/vector_store.py:93-125, 155-165
- app/rag_pipeline.py:84-100, 153-185, 276-307
- scripts/ingest_md.py:56-85
- docs/ONPREM_DEMO.md:4, 170 (원래 작업 트리의 미추적 문서: 로그인 없음, 계정·문서별 권한은 범위 밖)

## Verification / 재현

원본 재현 스크립트와 결과:
reports/local-judge/access-control-audit-20261008/probe.py 및 result.json.

    python -X utf8 reports/local-judge/access-control-audit-20261008/probe.py

실제 FastAPI 라우트를 TestClient로 호출하되 RAG 생성 함수만 합성 응답으로 대체했다.
개발 API와 on-prem API에 각각 네 가지 요청, 총 8가지를 실행했다.

| 요청 | 두 API의 결과 |
| --- | --- |
| 인증 없이 필터 생략 | HTTP 200, RAG 함수에 metadata_filter=None 전달 |
| 인증 없이 finance/confidential 필터 지정 | HTTP 200, 해당 필터를 그대로 전달 |
| 인증 없이 빈 필터 지정 | HTTP 200, metadata_filter=None 전달 |
| 검증되지 않은 marketing 헤더와 finance 필터 | HTTP 200, finance 필터 그대로 전달 |

마지막 헤더는 실제 인증 신원이 아니라 코드가 이를 권한으로 처리하지 않는다는 확인용이다.
이 8건은 **API 경계의 로컬 stub 재현**이며 실제 비공개 문서 유출 실험이 아니다.

실제 실행 서버에서는 인증 없이 localhost:8000/openapi.json을 읽을 수 있었으며,
securitySchemes와 질의 라우트/global security 설정이 없었다. Qdrant에는 인증 토큰 없이
읽기 전용 scroll을 실행해 현재 600개 payload의 권한 필드 유무만 집계했다.
실제 문서 본문은 보고서에 기록하지 않았다. LLM이나 외부 클라우드 API는 호출하지 않았다.

docker inspect로 현재 rag-api가 app.server:app을 실행하며 8000을 게시하는 것을 확인했다.
docker ps에서 Qdrant 6333과 API 8000이 0.0.0.0에 게시되어 있었다.
이는 호스트 바인딩 확인이며 인터넷 접근 가능성이나 방화벽 정책을 검증한 결과가 아니다.

## After / 결론과 한계

현재 제품은 단일 신뢰 영역의 문서 QA 시연 구조다. 다른 팀의 비공개 문서가 같은 검색 범위에
들어오면 현재 코드에는 사용자 신원을 근거로 제외하는 강제 경계가 없다.
기존에 사용자가 지정하는 부서 필터나 LAN 접근 제한을 문서별 인가로 설명하면 안 된다.

실제 문서별 ACL 및 역할별 계정이 구성되지 않았으므로 실제 권한 우회 성공률은 **측정하지 않음**이다.
외부에서 별도로 구성한 인증 게이트웨이나 조직 IAM은 조사하지 않았다. 저장소와 현재 로컬
컨테이너, 현재 collection에 대한 결론이며 다른 배포 환경에 일반화하지 않는다.

후속 구현에 필요한 경계는 검증된 로그인 신원 → 사용자/그룹 권한 → 문서 ACL → 서버 강제 검색
필터 → parent 문맥·출처 권한 확인이다. 역할을 프롬프트나 임의 헤더에서 신뢰하면 안 된다.
이후 허용 문서 정상 응답, 미허용 문서 직접 질문, 역할 사칭, 문서 내 우회 지시를 구분해 테스트해야 한다.

조사 소스는 원래 작업 트리 e2b00943e519ad951e94cb3d627b8e0ccfea1982와 로컬 미커밋/미추적 파일이다.
미추적 on-prem 파일을 이 조사 문서와 함께 제품 구현으로 게시하지 않는다.
