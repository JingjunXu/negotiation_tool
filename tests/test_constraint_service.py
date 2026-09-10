from negotiation_copilot import constraint_service
from negotiation_copilot.ai_client import (
    AIBottomlineDraft,
    AIRedlineDraft,
    AIReviewedText,
    ConstraintClassificationDraft,
    ConstraintRequest,
)
from negotiation_copilot.models import NegotiationCase, ReviewedText, WalkAwayAnalysis


def _reviewed(value: str) -> ReviewedText:
    return ReviewedText(current_value=value, ai_original_value=value, evidence_status="explicit", evidence=[])


class _StubConstraintClient:
    def __init__(self, draft: ConstraintClassificationDraft):
        self._draft = draft
        self.last_request: ConstraintRequest | None = None

    def classify_constraints(self, request: ConstraintRequest) -> ConstraintClassificationDraft:
        self.last_request = request
        return self._draft


def test_redline_candidates_are_never_pre_confirmed():
    draft = ConstraintClassificationDraft(
        redline_candidates=[
            AIRedlineDraft(
                statement=AIReviewedText(value="No payment beyond 60 days", evidence_status="explicit", evidence=[]),
                source_type="principal_mandate", consequence_if_crossed="Deal is void", evidence=[],
            )
        ],
        bottomline_candidates=[],
    )
    case = NegotiationCase()
    redlines, bottomlines = constraint_service.classify_constraints(case, None, ai_client=_StubConstraintClient(draft))

    assert len(redlines) == 1
    assert redlines[0].confirmed_by_user is False


# --- SPEC §14.1 item 19: a bottomline without a BATNA link stays provisional=True. ---
def test_bottomline_without_real_batna_link_stays_provisional():
    draft = ConstraintClassificationDraft(
        redline_candidates=[],
        bottomline_candidates=[
            AIBottomlineDraft(
                issue_id=None, threshold_value=AIReviewedText(value="$100k", evidence_status="inferred", evidence=[]),
                direction="min", rationale="x", linked_batna_reference="claims a link but none exists",
                risk_if_crossed="y", revisit_conditions=[], evidence=[],
            )
        ],
    )
    case = NegotiationCase()  # no walk_away passed at all
    redlines, bottomlines = constraint_service.classify_constraints(case, None, ai_client=_StubConstraintClient(draft))

    assert bottomlines[0].provisional is True
    assert bottomlines[0].linked_batna_reference is None  # claimed link discarded — no real BATNA backs it
    assert bottomlines[0].confirmed_by_user is False


def test_bottomline_with_real_batna_link_is_not_provisional():
    walk_away = WalkAwayAnalysis(
        my_batna=_reviewed("Secondary buyer"), batna_quality="moderate", quality_rationale="x",
        estimated_reservation_value=_reviewed("$100k"), reservation_derivation="x",
        counterpart_batna_hypothesis=None, exit_script="x",
    )
    draft = ConstraintClassificationDraft(
        redline_candidates=[],
        bottomline_candidates=[
            AIBottomlineDraft(
                issue_id=None, threshold_value=AIReviewedText(value="$100k", evidence_status="inferred", evidence=[]),
                direction="min", rationale="Matches reservation value", linked_batna_reference="estimated_reservation_value",
                risk_if_crossed="y", revisit_conditions=[], evidence=[],
            )
        ],
    )
    case = NegotiationCase()
    redlines, bottomlines = constraint_service.classify_constraints(case, walk_away, ai_client=_StubConstraintClient(draft))

    assert bottomlines[0].provisional is False
    assert bottomlines[0].linked_batna_reference == "estimated_reservation_value"


# --- SPEC §14.1 item 21: demote/promote preserve ai_original_value. ---
def test_demote_redline_to_bottomline_preserves_ai_original_value():
    from negotiation_copilot.models import Redline

    statement = _reviewed("No payment beyond 60 days")
    redline = Redline(statement=statement, source_type="principal_mandate", consequence_if_crossed="Void", confirmed_by_user=True)

    bottomline = constraint_service.demote_redline_to_bottomline(
        redline, direction="max", rationale="Actually negotiable with tradeoffs", risk_if_crossed="Cash flow strain"
    )

    assert bottomline.threshold_value is statement  # identity preserved
    assert bottomline.threshold_value.ai_original_value == "No payment beyond 60 days"
    assert bottomline.confirmed_by_user is False  # resets — different assertion now
    assert bottomline.provisional is True


def test_promote_bottomline_to_redline_preserves_ai_original_value():
    from negotiation_copilot.models import Bottomline

    threshold = _reviewed("$100k")
    bottomline = Bottomline(
        issue_id=None, threshold_value=threshold, direction="min", rationale="x",
        linked_batna_reference=None, risk_if_crossed="y", confirmed_by_user=True,
    )

    redline = constraint_service.promote_bottomline_to_redline(
        bottomline, source_type="principal_mandate", consequence_if_crossed="Deal is void"
    )

    assert redline.statement is threshold
    assert redline.statement.ai_original_value == "$100k"
    assert redline.confirmed_by_user is False
