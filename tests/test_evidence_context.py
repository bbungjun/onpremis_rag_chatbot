from app.evidence_context import EvidenceSource, compact_text, rank_sources, select_evidence


def source(number, text, *, document="a"):
    return EvidenceSource(
        f"jo-{number}", document, "규정", f"제{number}조", "", 1.0, text, document
    )


def test_compaction_preserves_scope_procedure_and_complete_negative_exception():
    text = (
        "제1조 (휴가)\n① [정의 및 목적]\n휴가 제도의 정의.\n"
        "② [적용 대상]\n정규직에게 적용한다.\n"
        "③ [세부 절차]\n승인을 신청한다.\n"
        "④ [예외 및 특수 상황]\n계약 기간이 짧은 사원은 신청할 수 없다.\n"
        "⑤ [위반 시 조치]\n위반 시 조치.\n⑥ [관련 서식]\n신청 서식."
    )
    compact = compact_text(text, "휴가 신청 절차는?")
    assert "정규직에게 적용한다." in compact
    assert "승인을 신청한다." in compact
    assert "계약 기간이 짧은 사원은 신청할 수 없다." in compact
    assert "휴가 제도의 정의." not in compact
    assert "신청 서식." not in compact


def test_requested_penalties_and_forms_are_not_removed():
    text = (
        "제1조\n③ [세부 절차]\n신청한다.\n⑤ [위반 시 조치]\n승인을 취소한다.\n"
        "⑥ [관련 서식]\n휴가 신청서."
    )
    assert "승인을 취소한다." in compact_text(text, "위반하면 어떤 처벌을 받나요?")
    assert "휴가 신청서." in compact_text(text, "어떤 서식으로 신청하나요?")


def test_reference_support_never_joins_another_document_or_external_law():
    anchor = source(1, "제1조 (출장)\n출장 신청은 제8조에 따른다. 민법 제9조도 참조한다.")
    plain = source(2, "제2조 (출장)\n출장 신청 안내.")
    wrong_document = source(8, "제8조 (출장)\n출장 신청 안내.", document="b")
    external_collision = source(9, "제9조 (출장)\n출장 신청 안내.")
    internal = source(8, "제8조 (출장)\n출장 신청 안내.")
    ranked = rank_sources(
        "출장 신청", [anchor, plain, wrong_document, external_collision, internal]
    )
    assert ranked[0] == anchor
    assert ranked.index(internal) < ranked.index(plain)
    assert ranked.index(plain) < ranked.index(wrong_document)
    assert ranked.index(plain) < ranked.index(external_collision)


def test_unsplittable_oversized_evidence_is_not_cut_into_misleading_sentences():
    item = source(1, "신청은 가능하지만 " + "조건을 확인한다. " * 100 + "해외에서는 금지한다.")

    def render(picked):
        return "질문\n" + "\n".join(s.text for s in picked)

    selected, prompt = select_evidence("신청 가능한가요?", [item], 5, 80, render)
    assert selected == []
    assert prompt == ""


def test_question_alone_over_budget_produces_no_evidence_prompt():
    selected, prompt = select_evidence(
        "긴 질문", [source(1, "짧은 근거")], 5, 10, lambda picked: "매우 긴 질문" * 10
    )
    assert (selected, prompt) == ([], "")


def test_unknown_section_labels_are_preserved_even_when_their_numbers_are_familiar():
    text = (
        "제1조\n① [필수 조건]\n서면 승인이 없으면 신청할 수 없다.\n⑤ [안전 조건]\n외부 반출 금지."
    )
    compact = compact_text(text, "신청 방법은?")
    assert "서면 승인이 없으면 신청할 수 없다." in compact
    assert "외부 반출 금지." in compact
