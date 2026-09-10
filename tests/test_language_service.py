from negotiation_copilot import language_service
from negotiation_copilot.ai_client import AIBilingualReplyDraft, AIEnglishVariantDraft
from negotiation_copilot.models import (
    AgreementItem,
    Bottomline,
    NegotiationAnalysis,
    NegotiationCase,
    Redline,
    ReviewedText,
    WalkAwayAnalysis,
)


def _reviewed(value: str) -> ReviewedText:
    return ReviewedText(current_value=value, ai_original_value=value, evidence_status="explicit", evidence=[])


def _base_case(**analysis_kwargs) -> NegotiationCase:
    return NegotiationCase(analysis=NegotiationAnalysis(**analysis_kwargs))


def _request(user_input="Can we settle at $120k?", do_not_disclose=None):
    from negotiation_copilot.models import LanguageDraftRequest

    return LanguageDraftRequest(
        mode="chinese_to_english", user_input=user_input, input_language="zh", tone="neutral",
        do_not_disclose=do_not_disclose or [],
    )


class _StubPhraseClient:
    def __init__(self, variants):
        self._variants = variants

    def phrase_in_english(self, request):
        return self._variants


class _StubReplyClient:
    def __init__(self, draft):
        self._draft = draft

    def draft_bilingual_reply(self, request):
        return self._draft


# --- SPEC §14.1 item 31: one fixture per risk flag. ---
def test_flags_reveals_batna():
    case = _base_case(walk_away=WalkAwayAnalysis(
        my_batna=_reviewed("Sell to a secondary buyer at a discount"), batna_quality="moderate", quality_rationale="x",
        estimated_reservation_value=None, reservation_derivation=None, counterpart_batna_hypothesis=None, exit_script="x",
    ))
    flags = language_service.check_risk_flags(["We could sell to a secondary buyer at a discount if needed."], "original input", case, [])
    assert "reveals_batna" in flags


def test_flags_reveals_reservation_value():
    case = _base_case(walk_away=WalkAwayAnalysis(
        my_batna=_reviewed("x"), batna_quality="moderate", quality_rationale="x",
        estimated_reservation_value=_reviewed("$100,000"), reservation_derivation="x",
        counterpart_batna_hypothesis=None, exit_script="x",
    ))
    flags = language_service.check_risk_flags(["Our floor is $100,000 no matter what."], "original", case, [])
    assert "reveals_reservation_value" in flags


def test_flags_reveals_bottomline_only_when_confirmed():
    bottomline = Bottomline(issue_id=None, threshold_value=_reviewed("$90,000"), direction="min", rationale="x", linked_batna_reference=None, risk_if_crossed="y", confirmed_by_user=True)
    case = _base_case(bottomlines=[bottomline])
    flags = language_service.check_risk_flags(["We won't go below $90,000."], "original", case, [])
    assert "reveals_bottomline" in flags

    unconfirmed_case = _base_case(bottomlines=[Bottomline(issue_id=None, threshold_value=_reviewed("$90,000"), direction="min", rationale="x", linked_batna_reference=None, risk_if_crossed="y", confirmed_by_user=False)])
    flags2 = language_service.check_risk_flags(["We won't go below $90,000."], "original", unconfirmed_case, [])
    assert "reveals_bottomline" not in flags2


def test_flags_crosses_redline_only_when_confirmed():
    redline = Redline(statement=_reviewed("Cannot accept payment terms beyond 60 days"), source_type="principal_mandate", consequence_if_crossed="Void", confirmed_by_user=True)
    case = _base_case(redlines=[redline])
    flags = language_service.check_risk_flags(["Cannot accept payment terms beyond 60 days, sorry."], "original", case, [])
    assert "crosses_redline" in flags


def test_flags_unconditional_concession_and_new_commitment():
    case = _base_case()
    flags = language_service.check_risk_flags(["We will lower the price to $95,000."], "Can we settle at $120k?", case, [])
    assert "new_commitment" in flags
    assert "unconditional_concession" in flags


def test_no_flags_when_conditional_and_no_new_numbers():
    case = _base_case()
    flags = language_service.check_risk_flags(["If you can confirm the timeline, we can discuss $120k."], "Can we settle at $120k?", case, [])
    assert "unconditional_concession" not in flags
    assert "new_commitment" not in flags


def test_flags_asserts_contested_fact_as_agreed():
    item = AgreementItem(kind="fact", statement="Delivery was completed on time", standing="contested")
    case = _base_case(agreement_landscape=[item])
    flags = language_service.check_risk_flags(["As we agreed, delivery was completed on time."], "original", case, [])
    assert "asserts_contested_fact_as_agreed" in flags


def test_flags_contradicts_confirmed_field_via_numeric_crossing():
    bottomline = Bottomline(issue_id=None, threshold_value=_reviewed("$100,000"), direction="min", rationale="x", linked_batna_reference=None, risk_if_crossed="y", confirmed_by_user=True)
    case = _base_case(bottomlines=[bottomline])
    flags = language_service.check_risk_flags(["We could accept $80,000 for this."], "original input with no numbers", case, [])
    assert "contradicts_confirmed_field" in flags


def test_do_not_disclose_terms_are_flagged():
    case = _base_case()
    flags = language_service.check_risk_flags(["Our internal budget cap is tight."], "original", case, ["internal budget cap"])
    assert "reveals_bottomline" in flags


# --- phrase_in_english / draft_bilingual_reply integration ---
def test_phrase_in_english_merges_ai_and_checked_flags():
    case = _base_case()
    stub = _StubPhraseClient([
        AIEnglishVariantDraft(label="natural", english_draft="We will pay $500 extra.", chinese_back_translation="我们将多付500美元。", risk_flags=["ai_self_flag"])
    ])
    variants = language_service.phrase_in_english(_request("Can we settle at $120k?"), case, ai_client=stub)

    assert len(variants) == 1
    assert "ai_self_flag" in variants[0].risk_flags
    assert "new_commitment" in variants[0].risk_flags  # $500 is a new number


def test_phrase_in_english_caps_at_three_variants():
    case = _base_case()
    stub = _StubPhraseClient([
        AIEnglishVariantDraft(label=label, english_draft="x", chinese_back_translation="x", risk_flags=[])
        for label in ["natural", "collaborative", "firm"]
    ] * 2)
    variants = language_service.phrase_in_english(_request(), case, ai_client=stub)
    assert len(variants) == 3


def test_draft_bilingual_reply_merges_flags():
    case = _base_case()
    draft = AIBilingualReplyDraft(
        counterpart_summary_zh="他们同意了。", counterpart_summary_en="They agreed.",
        points_to_verify=["Confirm delivery date"], chinese_draft="好的，我们同意。",
        english_draft="We will accept $999 immediately.", risk_flags=[],
    )
    result = language_service.draft_bilingual_reply(_request("Can we settle at $120k?"), case, ai_client=_StubReplyClient(draft))
    assert "new_commitment" in result.risk_flags


# --- SPEC §14.1 item 29: ZH->EN preserves numbers, conditions, negations, core intent. ---
def test_faithful_phrasing_of_number_condition_and_negation_raises_no_flags():
    case = _base_case()
    original = "如果他们不能在30天内付清120k，我们就不会同意。"
    faithful_english = "If they cannot pay the full 120k within 30 days, we will not agree."
    flags = language_service.check_risk_flags([faithful_english], original, case, [])
    # No new numbers introduced (120k, 30 both preserved) and the negation/condition survive as "if"/"not".
    assert "new_commitment" not in flags
    assert "unconditional_concession" not in flags


def test_stub_client_variant_preserving_input_produces_no_new_commitment_flag():
    case = _base_case()
    stub = _StubPhraseClient([
        AIEnglishVariantDraft(
            label="natural", english_draft="If we don't receive the 120k within 30 days, the deal is off.",
            chinese_back_translation="如果我们没有在30天内收到120k，交易就取消。", risk_flags=[],
        )
    ])
    variants = language_service.phrase_in_english(
        _request("如果我们没有在30天内收到120k，交易就取消。"), case, ai_client=stub
    )
    assert "new_commitment" not in variants[0].risk_flags


# --- SPEC §14.1 item 30: counterpart input in either language yields
# semantically consistent ZH and EN drafts (both languages always produced). ---
def test_bilingual_reply_produces_both_languages_from_english_input():
    case = _base_case()
    draft = AIBilingualReplyDraft(
        counterpart_summary_zh="他们要求延期。", counterpart_summary_en="They asked for an extension.",
        points_to_verify=["Confirm new date"], chinese_draft="好的，我们可以考虑延期。",
        english_draft="Understood, we can consider an extension.", risk_flags=[],
    )
    result = language_service.draft_bilingual_reply(
        _request("They asked us for a two-week extension on delivery."), case, ai_client=_StubReplyClient(draft)
    )
    assert result.chinese_draft
    assert result.english_draft
    assert result.counterpart_summary_zh and result.counterpart_summary_en


def test_bilingual_reply_produces_both_languages_from_chinese_input():
    case = _base_case()
    draft = AIBilingualReplyDraft(
        counterpart_summary_zh="他们要求延期。", counterpart_summary_en="They asked for an extension.",
        points_to_verify=["Confirm new date"], chinese_draft="好的，我们可以考虑延期。",
        english_draft="Understood, we can consider an extension.", risk_flags=[],
    )
    result = language_service.draft_bilingual_reply(
        _request("他们要求两周的交货延期。"), case, ai_client=_StubReplyClient(draft)
    )
    assert result.chinese_draft
    assert result.english_draft
    assert result.counterpart_summary_zh and result.counterpart_summary_en


def test_build_language_context_excludes_walk_away_and_limits_even_if_selected():
    from negotiation_copilot.models import BriefSectionState, NegotiationBrief

    brief = NegotiationBrief(sections=[
        BriefSectionState(section_id="walk_away_position", title="Walk-Away Position (private)", ai_generated_base="BATNA: secret info"),
        BriefSectionState(section_id="objective_success_criteria", title="Objective", ai_generated_base="Secure renewal"),
    ])
    request = _request()
    request.selected_brief_section_ids = ["walk_away_position", "objective_success_criteria"]
    case = _base_case()

    context = language_service.build_language_context(request, case, brief)
    assert "secret info" not in context
    assert "Secure renewal" in context
