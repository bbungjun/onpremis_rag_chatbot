"""질문 해석 — 사용자 문장 하나를 검색용/답변용으로 나눈다.

RAG 파이프라인의 첫 단계다. 검색보다 먼저 돌며, 사용자가 입력한 문장 하나를
다음 세 가지 용도로 쪼갠다.

  - retrieval_question : 벡터화되어 Qdrant 검색에만 쓰인다.
  - canonical_question : "무엇을 어떻게 답하라"는 지시문이 붙은 질문. LLM 프롬프트로 간다.
  - original_question  : 사용자 어투 보존용. 함께 프롬프트로 가서 답변 표현의 기준이 된다.

검색에 유리한 표현과 답변 지시에 유리한 표현이 다르기 때문에 문장을 나눈다.

이 모듈은 LLM 을 호출하지 않는다. import 가 re 와 dataclass 뿐인 순수 규칙 기반이다.
온프레미스에서 질의당 추가 모델 호출을 늘리지 않으려는 선택이고, 대가는 커버리지다.
아래 마커 목록에 없는 표현은 GENERAL_QA 로 떨어져 지시문 보강을 받지 못한다.

처리 순서 (interpret_question 참고):
    정규화 -> 조건 추출 -> 의도 분류 -> 검색 문장 확정 -> 정규 질문 조립
각 단계는 앞 단계 결과에 의존하므로 순서를 바꾸면 동작이 달라진다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# intent 값. 앞의 넷은 "문서에 뭐라고 적혀 있나"(조회)이고,
# ELIGIBILITY_CHECK 만 "내 상황이 그 기준에 맞나"(판정)라서 지시문이 훨씬 길다.
DEADLINE_LOOKUP = "deadline_lookup"
ELIGIBILITY_CHECK = "eligibility_check"
PROCEDURE_LOOKUP = "procedure_lookup"
REQUIREMENT_LOOKUP = "requirement_lookup"
GENERAL_QA = "general_qa"

# 의도 판정용 마커. 전부 부분 문자열 포함 검사(_contains_any)로만 쓰인다.
# 단어 경계를 보지 않으므로 "불가능"이 "가능"에 걸리는 식의 오분류가 있을 수 있다.
_ANNUAL_LEAVE_TERMS = ("연차", "휴가", "유급휴가")
_ANNUAL_LEAVE_ACTIONS = (
    "신청",
    "사용",
    "쓰",
    "써",
    "넣",
)
_ELIGIBILITY_FALLBACK_MARKERS = (
    "될까요",
    "되나요",
    "가능",
    "괜찮",
    "문제 없",
    "문제없",
    "해도 되",
    "할 수 있",
)
_DEADLINE_MARKERS = ("언제까지", "며칠 전까지", "몇 일 전까지", "기한", "마감")
_PROCEDURE_MARKERS = ("절차", "방법", "어떻게", "순서", "신청 방법")
_REQUIREMENT_MARKERS = ("필요", "필수", "증빙", "서류", "조건")


@dataclass(frozen=True)
class InterpretedQuestion:
    """해석 결과. 각 필드가 파이프라인의 서로 다른 목적지로 간다.

    Attributes:
        original_question: 사용자 원문(공백만 정리). 프롬프트의 [original_question] 블록.
        intent: 아래 5종 상수 중 하나. canonical 지시문 선택과 내부 분기에 쓰인다.
        canonical_question: 지시문이 붙은 질문. 프롬프트의 [canonical_question] 블록.
        conditions: 문장에서 뽑아낸 사용자 조건(lead_time / amount / missing_evidence).
        retrieval_question: 검색 전용 문장. dense 임베딩과 sparse 벡터가 이 문장으로 만들어진다.
    """

    original_question: str
    intent: str
    canonical_question: str
    conditions: dict[str, str]
    retrieval_question: str


def interpret_question(question: str) -> InterpretedQuestion:
    """질문 하나를 5개 필드로 해석한다. 이 모듈의 유일한 공개 함수다.

    단계가 순서에 의존한다는 점이 중요하다. 예를 들어 "사흘 뒤"는 정규화 단계에서
    "3일 뒤"가 되어야 조건 추출의 숫자 정규식에 걸리고, 조건이 뽑혀야 의도 분류의
    구조 판정이 동작하고, 그 의도가 있어야 검색 문장 교체가 일어난다.

    normalized_question 은 반환하지 않는다. 2~5단계의 재료로만 쓰이는 중간값이다.
    """
    original_question = question.strip()
    normalized_question = _normalize_retrieval_question(original_question)
    conditions = _extract_conditions(normalized_question)
    intent = _classify_intent(normalized_question, conditions)
    retrieval_question = _build_retrieval_question(normalized_question, intent, conditions)
    canonical_question = _build_canonical_question(
        original_question,
        normalized_question,
        intent,
        conditions,
    )
    return InterpretedQuestion(
        original_question=original_question,
        intent=intent,
        canonical_question=canonical_question,
        conditions=conditions,
        retrieval_question=retrieval_question,
    )


def _classify_intent(question: str, conditions: dict[str, str]) -> str:
    """질문이 무엇을 요구하는지 5종 중 하나로 분류한다.

    첫 매치에서 즉시 반환하는 if 체인이라 순서가 곧 우선순위다. 여러 의도가 섞인
    질문("절차는 어떻게 되고 며칠 전까지 해야 하나요")은 먼저 걸린 하나만 이긴다.

    ELIGIBILITY_CHECK 가 맨 앞과 맨 뒤에 두 번 나오는 것이 이 함수의 특징이다.
      - 앞(구조 판정): 조건이 실제로 추출된 연차 질문. "기한" 같은 단어 때문에
        DEADLINE_LOOKUP 으로 먼저 채이는 것을 막으려고 앞에 둔다.
      - 뒤(표현 판정): "될까요" 같은 어미로만 판단하는 넓은 그물.
    """
    if _is_structural_annual_leave_eligibility(question, conditions):
        return ELIGIBILITY_CHECK
    if _contains_any(question, _DEADLINE_MARKERS):
        return DEADLINE_LOOKUP
    if _contains_any(question, _PROCEDURE_MARKERS):
        return PROCEDURE_LOOKUP
    if _contains_any(question, _REQUIREMENT_MARKERS):
        return REQUIREMENT_LOOKUP
    if _contains_any(question, _ELIGIBILITY_FALLBACK_MARKERS):
        return ELIGIBILITY_CHECK
    return GENERAL_QA


def _extract_conditions(question: str) -> dict[str, str]:
    """문장에서 사용자의 상황을 뽑아 dict 로 만든다.

    문서 기준과 비교할 대상이 되는 값들이다. 뽑히지 않으면 키 자체를 넣지 않으므로,
    빈 dict 는 "조건 없는 단순 조회 질문"이라는 신호로 쓰인다.

    Returns:
        lead_time / amount / missing_evidence 중 발견된 것만 담긴 dict.
    """
    conditions: dict[str, str] = {}
    lead_time = _extract_lead_time(question)
    if lead_time:
        conditions["lead_time"] = lead_time
    amount = _extract_amount(question)
    if amount:
        conditions["amount"] = amount
    if any(marker in question for marker in ("영수증 없", "증빙 없", "분실")):
        conditions["missing_evidence"] = "true"
    return conditions


def _extract_lead_time(question: str) -> str | None:
    """사용 예정 시점을 뽑는다. "3일 뒤", "당일", "내일" 형태로 정규화한다.

    숫자 패턴을 먼저 보고, 없으면 상대 표현을 본다. "사흘 뒤" 같은 고유어는
    이 함수가 아니라 _replace_relative_day_words 가 앞서 "3일 뒤"로 바꿔 둔다.
    """
    explicit = re.search(r"(\d+\s*일)\s*(뒤|후|전)(?:에|로|부터)?", question)
    if explicit:
        return f"{explicit.group(1).replace(' ', '')} {explicit.group(2)}"
    if "당일" in question or "오늘" in question:
        return "당일"
    if "내일" in question:
        return "내일"
    return None


def _extract_amount(question: str) -> str | None:
    """금액을 뽑아 공백을 제거한 문자열로 돌려준다. "5 만 원" -> "5만원"."""
    match = re.search(r"(\d+\s*(?:만\s*)?원)", question)
    if match:
        return re.sub(r"\s+", "", match.group(1))
    return None


def _build_canonical_question(
    original_question: str,
    retrieval_question: str,
    intent: str,
    conditions: dict[str, str],
) -> str:
    """intent 에 맞는 지시문을 붙여 LLM 에 넘길 질문을 만든다.

    조회 의도(DEADLINE / PROCEDURE / REQUIREMENT)는 "문서에 적힌 것을 답하라"는
    한 줄이면 되지만, 판정 의도(ELIGIBILITY_CHECK)는 비교 규칙까지 알려줘야 해서
    지시문이 훨씬 길다. GENERAL_QA 는 붙일 지시문이 없어 원문을 그대로 돌려준다.

    Note:
        두 번째 인자 이름은 retrieval_question 이지만 호출부(interpret_question)는
        normalized_question 을 넘긴다. 이 값은 _is_annual_leave_deadline_check 에서
        "연차" 포함 여부만 보는데 교체된 검색 문장에도 "연차"가 들어 있어 결과는 같다.
        이름만 어긋난 것이니 추적할 때 혼동하지 말 것.
    """
    if intent == GENERAL_QA:
        return original_question

    if intent == ELIGIBILITY_CHECK:
        # 연차 기한 판정은 영업일/달력일 비교까지 필요해 전용 지시문을 쓴다.
        if _is_annual_leave_deadline_check(retrieval_question, conditions):
            lead_time = conditions["lead_time"]
            return (
                f"원 질문: {original_question}\n"
                f"해석된 질문: 사용자는 연차를 {lead_time}에 사용하려고 한다. "
                "문서에 명시된 연차 신청 기한 기준을 찾고, 이 조건이 기준을 충족하는지 판단하라.\n"
                f"사용자 조건: 사용 예정 시점={lead_time}\n"
                f"비교 방식: 사용일까지 남은 기간은 {_lead_time_to_days_text(lead_time)}이다. "
                "context에 '최소 M영업일 전' 또는 '최소 M일 전' 기준이 있으면, "
                "사용자 조건과 문서 기준 M을 비교하라. "
                "사용자 조건이 M보다 짧으면 기준을 충족하지 않는다고 답하라. "
                "사용자 조건이 M 이상이면 기준을 충족한다고 답하라. "
                "다만 기준이 영업일이고 사용자 조건이 달력일 기준이면, "
                "주말/공휴일 여부 확인이 필요하다고 조건부로 표현하라.\n"
                "문서 기준상 충족하지 않으면 필요한 최소 신청 기한을 답하라. "
                "새 날짜를 계산하지 말라. "
                "문서에 없는 승인, 거부, 예외, 추측은 만들지 말라."
            )

        # 그 외 판정 질문. 조건이 비어 있어도(어미만 보고 걸린 경우) 여기로 온다.
        condition_text = _format_conditions(conditions)
        return (
            f"원 질문: {original_question}\n"
            "해석된 질문: 사용자의 상황이 문서 기준상 허용되거나 "
            "필요한 요건을 충족하는지 판단하라.\n"
            f"사용자 조건: {condition_text}\n"
            "문서에 명시된 기준과 사용자 조건을 비교해 충족 여부를 답하라. "
            "문서에 없는 승인 재량, 예외, 추측은 만들지 말라."
        )

    if intent == DEADLINE_LOOKUP:
        return (
            f"원 질문: {original_question}\n"
            "해석된 질문: 문서에 명시된 기한, 마감일, 사전 신청 기준을 답하라."
        )

    if intent == PROCEDURE_LOOKUP:
        return (
            f"원 질문: {original_question}\n"
            "해석된 질문: 문서에 명시된 신청, 승인, 보고, 처리 절차를 순서대로 답하라."
        )

    # 남은 경우는 REQUIREMENT_LOOKUP 뿐이다.
    return (
        f"원 질문: {original_question}\n"
        "해석된 질문: 문서에 명시된 필수 요건, 조건, 증빙 또는 서류를 답하라."
    )


def _format_conditions(conditions: dict[str, str]) -> str:
    """조건 dict 를 프롬프트에 넣을 한 줄로 만든다. "lead_time=3일 뒤, amount=5만원"."""
    if not conditions:
        return "명시적으로 추출된 조건 없음"
    return ", ".join(f"{key}={value}" for key, value in conditions.items())


def _is_structural_annual_leave_eligibility(question: str, conditions: dict[str, str]) -> bool:
    """연차 판정 질문인지 '구조'로 본다. 어미가 아니라 세 조건의 AND 다.

    시점이 실제로 추출됐고(lead_time) + 연차 계열 단어가 있고 + 행동 단어가 있을 때만
    참이다. 그래서 단순 조회 질문이 판정으로 잘못 분류되는 것을 막는다.
    """
    return (
        "lead_time" in conditions
        and _contains_any(question, _ANNUAL_LEAVE_TERMS)
        and _contains_any(question, _ANNUAL_LEAVE_ACTIONS)
    )


def _is_annual_leave_deadline_check(question: str, conditions: dict[str, str]) -> bool:
    """연차 기한 전용 처리를 쓸지 판단한다. 검색 문장 교체와 전용 지시문이 여기에 걸린다."""
    return "연차" in question and "lead_time" in conditions


def _lead_time_to_days_text(lead_time: str) -> str:
    """지시문에 넣을 기간 표현을 만든다. "3일 뒤" -> "3일", "내일" -> "내일"."""
    day_count = re.match(r"(\d+)일", lead_time)
    if day_count:
        return f"{day_count.group(1)}일"
    return lead_time


def _contains_any(text: str, markers: tuple[str, ...]) -> bool:
    """마커 중 하나라도 부분 문자열로 들어 있으면 True.

    단어 경계를 보지 않는다. "불가능"에 "가능"이 걸리는 식의 오분류가 여기서 나온다.
    """
    return any(marker in text for marker in markers)


def _normalize_retrieval_question(question: str) -> str:
    """표기 흔들림을 없앤다. 뒤의 모든 단계가 문자열 매칭이라 여기가 어긋나면 전부 무너진다.

    셋을 순서대로 한다.
      1. 고유어 날짜를 숫자로 ("사흘 뒤" -> "3일 뒤"). 이래야 조건 추출 정규식에 걸린다.
      2. 자주 흔들리는 표현의 띄어쓰기 통일. 문서 쪽 표기와 맞춰야 BM25 토큰이 겹친다.
      3. 연속 공백을 하나로.
    """
    normalized = question.strip()
    normalized = _replace_relative_day_words(normalized)
    replacements = (
        (r"연차\s*신청", "연차 신청"),
        (r"출장비\s*정산", "출장비 정산"),
        (r"경비\s*처리", "경비 처리"),
        (r"재택근무\s*승인", "재택근무 승인"),
        (r"해도\s*될까요", "해도 될까요"),
        (r"할\s*수\s*있나요", "할 수 있나요"),
        (r"며칠\s*전까지", "며칠 전까지"),
        (r"몇\s*일\s*전까지", "몇 일 전까지"),
    )
    for pattern, replacement in replacements:
        normalized = re.sub(pattern, replacement, normalized)
    return re.sub(r"\s+", " ", normalized).strip()


def _build_retrieval_question(
    normalized_question: str,
    intent: str,
    conditions: dict[str, str],
) -> str:
    """검색에 쓸 문장을 정한다. 딱 한 경우만 교체하고 나머지는 정규화된 원문 그대로다.

    연차 기한 판정 질문은 사용자 표현("3일 뒤에 써도 될까요")이 규정 원문과 너무
    달라 검색이 잘 걸리지 않는다. 그래서 조문 어휘에 가까운 고정 문장으로 바꾼다.
    규칙 기반 질의 재작성이고, 대가는 규칙 밖 표현이 그대로 통과한다는 점이다.
    """
    if intent == ELIGIBILITY_CHECK and _is_annual_leave_deadline_check(
        normalized_question,
        conditions,
    ):
        return "연차 유급휴가 신청 기한 최소 영업일 전"
    return normalized_question


def _replace_relative_day_words(question: str) -> str:
    """고유어 날짜를 숫자 표기로 바꾼다. 뒤/후/전이 따라올 때만 치환한다.

    "하루 종일" 같은 표현까지 건드리지 않으려고 뒤따르는 방향어를 조건으로 건다.
    """
    day_words = {
        "하루": "1일",
        "이틀": "2일",
        "사흘": "3일",
        "나흘": "4일",
    }
    normalized = question
    for word, replacement in day_words.items():
        normalized = re.sub(rf"{word}\s*(뒤|후|전)", rf"{replacement} \1", normalized)
    return normalized
