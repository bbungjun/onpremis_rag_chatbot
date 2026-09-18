# 사내 규정 답변은 로컬 추론을 기본 경로로 둔다

상태: accepted. 직원 질문과 검색된 규정 문맥을 외부 LLM API에 보낼 때 생기는 데이터 경계와 토큰별 사용료를 피하기 위해, 기본 RAG 답변은 호스트 Ollama의 Qwen으로, 임베딩은 로컬 bge-m3로 수행한다. Qdrant와 애플리케이션은 자체 운영 환경에 둔다. 이 선택은 GPU·전력·운영·장애 대응 비용을 직접 부담하며, 로컬 실행만으로 접근 제어와 기밀성이 완성되지는 않는다. Gemini 비교 경로와 개발용 Compose는 제품 배포 경계에서 별도로 차단해야 한다. [현재 설정](../../app/config.py), [생성 클라이언트](../../app/qwen_client.py), [배포 격차](../RAG_ARCHITECTURE_RATIONALE.md).
