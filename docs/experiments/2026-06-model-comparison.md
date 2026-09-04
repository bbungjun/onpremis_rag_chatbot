# 2026-06 모델 비교 관찰 기록

README에 있던 6월 팀 온보딩 시점의 관찰 기록을 옮긴 문서입니다. 아래 수치는 모두 **단일 질문,
단일 실행** 관찰이며 통제된 벤치마크가 아닙니다. 채택된 평가 결과는
`docs/portfolio/2026-08-31-rrf-ablation-reranker-evaluation.md`를 따릅니다.

## 당시 역할 분담

### 1. RAG 성능 개선 담당

LLM 모델은 고정하고 RAG 파이프라인 병목을 줄이는 역할.

```text
[1/4] Embedding question
[2/4] Searching Qdrant (dense + BM25 하이브리드)
[3/4] Expanding to parent articles
[4/4] LLM generation
```

우선순위:

```text
1. embedding latency 측정 및 개선
2. top_k와 RRF dense/sparse 가중치 조합별 retrieval 품질/속도 비교
3. context 길이(조 전체 확장)가 답변 품질과 생성 속도에 주는 영향 확인
4. dense 단독 vs dense+BM25 하이브리드의 검색 품질 비교
5. Qdrant 하이브리드 검색 latency 측정
6. 동일 질문 반복 시 embedding cache 또는 query result cache 검토
```

이 중 2, 4, 5는 2026-08-31 ablation으로 수행했다.

### 2. LLM 모델 변경 및 속도 측정 담당

RAG 검색 흐름은 그대로 두고 생성 모델만 바꾸며 속도와 답변 품질을 비교하는 역할.

측정 기준: LLM generation time, end-to-end latency, RAM, 한국어 출력 여부, 불필요한 thinking
출력 여부, 문서 근거 여부, max output token 안에서 끊기지 않는지.

## 2026-06-18 관찰

### 모델별 생성 시간 (단일 질문)

```text
qwen3:4b
- NUM_PREDICT=256
- Qwen generation: 약 45.237s
- 영어 reasoning이 출력되어 QA 응답 품질이 낮았음
  (이후 2026-08-03에 qwen3 계열은 think=true로 보내 reasoning과 content를 분리하도록 수정)

qwen3:4b-instruct
- NUM_PREDICT=192, NUM_CTX=2048, top_k=3
- Qwen generation: 약 28.692s

gemini-2.5-flash
- 동일 RAG 검색 결과를 Vertex API로 생성, thinking_budget=0
- Gemini generation: 약 2.1s ~ 3.3s
```

### RAG 하네스 vs 순수 모델 비교

질문: "법인카드 사용 후 전표 처리는 언제까지 해야 하나요?"

동일하게 적용한 하네스: dense(bge-m3) + sparse(BM25) -> Qdrant 하이브리드 검색(RRF) -> 조(parent)
확장 -> grounded prompt -> 출처 출력.

| Model | 실행 위치 | Generation | 핵심 답변 | Source |
| --- | --- | ---: | --- | --- |
| gemini-2.5-flash | Vertex API | 2.415s | 법인카드 사용 후 7영업일 이내에 사용 목적과 참석자(해당 시)를 명시하여 전표 처리 | regulations.md#jo-62 |
| qwen2.5:7b | AWS EC2 g4dn.xlarge + Ollama | 4.725s | 법인카드 사용 후 7영업일 이내에 전표 처리하며 업무 관련 비용에 한해 사용 가능 | regulations.md#jo-62 |

RAG 없는 일반 지식 질문(피타고라스 정리 설명):

| Model | Generation | 품질 메모 |
| --- | ---: | --- |
| gemini-2.5-flash | 6.114s | 개념, 공식, 3-4-5 예시를 정확하게 설명 |
| qwen2.5:7b | 4.043s warm / 40.313s cold | 공식과 계산은 맞았지만 "둘레 길이에 대한 규칙"이라는 개념 표현 오류 |

당시 해석: 일반 지식에서는 Gemini가 우위였지만, 문서 근거가 충분한 정책 질문에서는 RAG 하네스를
거치면 두 모델의 핵심 답변과 출처가 거의 일치했다. 단일 질문 관찰이므로 일반화하지 않는다.

### 실험 기록 표

| Date | Model | NUM_CTX | NUM_PREDICT | top_k | Embedding | Search | Generation | 메모 |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| 2026-06-18 | qwen3:4b | default | 256 | 5 | 0.456s | 0.033s | 45.237s | 영어 reasoning 출력 |
| 2026-06-18 | qwen3:4b-instruct | 2048 | 192 | 3 | 1.966s | 0.030s | 28.692s | 한국어 답변 정상 |
| 2026-06-18 | gemini-2.5-flash | - | 256 | 3 | 0.519s | 0.064s | 2.126s | 답변 정상 |
| 2026-06-18 | gemini-2.5-flash(RAG) | - | 256 | 3 | 3.409s | 0.184s | 2.415s | Qwen과 핵심 답변·source 거의 일치 |
| 2026-06-18 | qwen2.5:7b(RAG) | default | 256 | 3 | 2.417s | 0.193s | 4.725s | EC2 GPU |
| 2026-06-18 | gemini-2.5-flash(순수) | - | 512 | - | - | - | 6.114s | 설명 정확 |
| 2026-06-18 | qwen2.5:7b(순수) | default | 512 | - | - | - | 4.043s warm | 개념 표현 오류, cold 40.313s |
