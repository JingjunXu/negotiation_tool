from negotiation_copilot import walkaway_service
from negotiation_copilot.ai_client import AIReviewedText, AIWalkAwayDraft, WalkAwayRequest
from negotiation_copilot.models import NegotiationCase, ReviewedText


def _reviewed(value: str) -> ReviewedText:
    return ReviewedText(current_value=value, ai_original_value=value, evidence_status="explicit", evidence=[])


class _StubWalkAwayClient:
    def __init__(self, draft: AIWalkAwayDraft):
        self._draft = draft

    def analyze_walk_away(self, request: WalkAwayRequest) -> AIWalkAwayDraft:
        return self._draft


def _draft(**overrides) -> AIWalkAwayDraft:
    defaults = dict(
        my_batna=AIReviewedText(value="Sell to a secondary buyer", evidence_status="inferred", evidence=[]),
        batna_quality="moderate",
        quality_rationale="Secondary buyer confirmed interest.",
        actions_to_improve_batna=[],
        estimated_reservation_value=AIReviewedText(value="$100k", evidence_status="inferred", evidence=[]),
        reservation_derivation="10% below primary ask.",
        counterpart_batna_hypothesis=None,
        tests_to_probe_their_batna=[],
        walk_away_triggers=[],
        exit_script="We appreciate the discussion but cannot proceed on these terms today.",
        do_not_disclose=["reservation_value"],
    )
    defaults.update(overrides)
    return AIWalkAwayDraft(**defaults)


# --- SPEC §14.1 item 18: reservation value is null and a gap is raised when batna_quality == "unknown". ---
def test_unknown_batna_quality_nulls_reservation_value_and_raises_gap():
    case = NegotiationCase()
    draft = _draft(batna_quality="unknown")
    analysis, warnings = walkaway_service.analyze_walk_away(case, ai_client=_StubWalkAwayClient(draft))

    assert analysis.batna_quality == "unknown"
    assert analysis.estimated_reservation_value is None
    assert any("preparation gap" in w.lower() for w in warnings)


# --- Aspiration must never be used as reservation value. ---
def test_reservation_value_matching_target_is_discarded():
    case = NegotiationCase(targets=[_reviewed("$200k")])
    draft = _draft(batna_quality="weak", estimated_reservation_value=AIReviewedText(value="$200k", evidence_status="inferred", evidence=[]))
    analysis, warnings = walkaway_service.analyze_walk_away(case, ai_client=_StubWalkAwayClient(draft))

    assert analysis.estimated_reservation_value is None
    assert any("aspiration" in w.lower() or "target" in w.lower() for w in warnings)


def test_reservation_value_matching_issue_target_is_discarded():
    from negotiation_copilot.models import NegotiationIssue

    issue = NegotiationIssue(title="Price", target=_reviewed("$200k"))
    case = NegotiationCase(issues=[issue])
    draft = _draft(batna_quality="weak", estimated_reservation_value=AIReviewedText(value="$200k", evidence_status="inferred", evidence=[]))
    analysis, warnings = walkaway_service.analyze_walk_away(case, ai_client=_StubWalkAwayClient(draft))

    assert analysis.estimated_reservation_value is None
    assert warnings


def test_normal_reservation_value_is_preserved():
    case = NegotiationCase(targets=[_reviewed("$200k")])
    draft = _draft(batna_quality="moderate", estimated_reservation_value=AIReviewedText(value="$100k", evidence_status="inferred", evidence=[]))
    analysis, warnings = walkaway_service.analyze_walk_away(case, ai_client=_StubWalkAwayClient(draft))

    assert analysis.estimated_reservation_value.current_value == "$100k"
    assert warnings == []


def test_walk_away_always_produces_exit_script():
    case = NegotiationCase()
    draft = _draft()
    analysis, _ = walkaway_service.analyze_walk_away(case, ai_client=_StubWalkAwayClient(draft))
    assert analysis.exit_script
