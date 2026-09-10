from negotiation_copilot import brief_service
from negotiation_copilot.fake_clients import FakeAIClient
from negotiation_copilot.models import (
    AgreementItem,
    Bottomline,
    HagglePlan,
    InterestItem,
    NegotiationAnalysis,
    NegotiationCase,
    Redline,
    ReviewedText,
    TradeCurrency,
    TradePackage,
    WalkAwayAnalysis,
)


def _reviewed(value: str) -> ReviewedText:
    return ReviewedText(current_value=value, ai_original_value=value, evidence_status="explicit", evidence=[])


def _plan_with_packages(n: int) -> HagglePlan:
    packages = [
        TradePackage(label=f"Package {i}", option_ids=[], what_i_give=[], what_i_get=[], equivalence_note="x")
        for i in range(n)
    ]
    return HagglePlan(anchor="$130k", justification_standard="Market rate", trade_currencies=[], packages=packages)


# --- SPEC §14.1 item 27: Live Card contains walk-away, redlines, top interests,
# islands, packages, and questions, all within the size cap. ---
def test_live_card_caps_every_list_at_three_items():
    interests = [InterestItem(party="me", category="need", statement=_reviewed(f"Need {i}")) for i in range(6)]
    interests += [InterestItem(party="counterpart", category="need", statement=_reviewed(f"Their need {i}"), is_hypothesis=True) for i in range(6)]
    shared_items = [AgreementItem(kind="fact", statement=f"Shared fact {i}", standing="shared") for i in range(6)]
    walk_away = WalkAwayAnalysis(
        my_batna=_reviewed("Secondary buyer"), batna_quality="moderate", quality_rationale="x",
        estimated_reservation_value=_reviewed("$100k"), reservation_derivation="x",
        counterpart_batna_hypothesis=None, exit_script="x",
    )
    redline = Redline(statement=_reviewed("No terms beyond 60 days"), source_type="principal_mandate", consequence_if_crossed="Void", confirmed_by_user=True)

    case = NegotiationCase(
        analysis=NegotiationAnalysis(
            interests=interests, agreement_landscape=shared_items, walk_away=walk_away,
            redlines=[redline], haggle_plan=_plan_with_packages(6),
        )
    )
    brief = brief_service.generate_brief(case, ai_client=FakeAIClient())
    card = brief_service.build_live_card(case, brief)

    assert len(card.my_top_interests) <= 3
    assert len(card.their_top_interests) <= 3
    assert len(card.shared_facts_opener) <= 3
    assert len(card.packages) <= 3
    assert len(card.next_questions) <= 3
    assert "Secondary buyer" in card.walk_away_line
    assert "No terms beyond 60 days" in card.redlines


def test_live_card_unconfirmed_redline_never_shown():
    redline = Redline(statement=_reviewed("Unconfirmed redline"), source_type="principal_mandate", consequence_if_crossed="Void", confirmed_by_user=False)
    case = NegotiationCase(analysis=NegotiationAnalysis(redlines=[redline]))
    card = brief_service.build_live_card(case)
    assert card.redlines == []


def test_live_card_works_without_a_brief():
    case = NegotiationCase()
    card = brief_service.build_live_card(case)
    assert card.walk_away_line == "Not established"
    assert card.next_questions == []
    assert card.pinned_sections == []


def test_live_card_includes_pinned_sections():
    case = NegotiationCase()
    brief = brief_service.generate_brief(case, ai_client=FakeAIClient())
    brief.sections[0].pinned = True
    card = brief_service.build_live_card(case, brief)
    assert len(card.pinned_sections) == 1
    assert card.pinned_sections[0].section_id == brief.sections[0].section_id
