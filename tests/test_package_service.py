import pytest
from pydantic import ValidationError

from negotiation_copilot import package_service
from negotiation_copilot.ai_client import (
    AIConcessionStepDraft,
    AIPackageDraft,
    HaggleRequest,
    HagglePlanDraft,
)
from negotiation_copilot.models import (
    Bottomline,
    ConcessionStep,
    CounterTactic,
    HagglePlan,
    InterestItem,
    NegotiationCase,
    NegotiationOption,
    Redline,
    ReviewedText,
    TradePackage,
)


def _reviewed(value: str) -> ReviewedText:
    return ReviewedText(current_value=value, ai_original_value=value, evidence_status="explicit", evidence=[])


def _option(**overrides) -> NegotiationOption:
    defaults = dict(
        title="Staged payments", description="x", option_type="time",
        serves_my_interest_ids=[], serves_their_interest_ids=[],
        cost_to_me="low", value_to_them_hypothesis="medium", evidence_status="inferred",
    )
    defaults.update(overrides)
    return NegotiationOption(**defaults)


def _bottomline(direction: str, threshold: str, issue_id=None, confirmed=True) -> Bottomline:
    return Bottomline(
        issue_id=issue_id, threshold_value=_reviewed(threshold), direction=direction, rationale="x",
        linked_batna_reference=None, risk_if_crossed="y", confirmed_by_user=confirmed,
    )


def _redline(statement: str, confirmed=True) -> Redline:
    return Redline(statement=_reviewed(statement), source_type="principal_mandate", consequence_if_crossed="Void", confirmed_by_user=confirmed)


class _StubHaggleClient:
    def __init__(self, draft: HagglePlanDraft):
        self._draft = draft

    def build_haggle_plan(self, request: HaggleRequest) -> HagglePlanDraft:
        return self._draft


# --- Model-level guarantee backing SPEC item 26. ---
def test_haggleplan_rejects_empty_justification_standard_at_model_level():
    with pytest.raises(ValidationError):
        HagglePlan(anchor="x", justification_standard="   ")


def test_concession_step_rejects_empty_ask_in_return_at_model_level():
    with pytest.raises(ValidationError):
        ConcessionStep(order=1, issue_id=None, from_value="a", to_value="b", ask_in_return="", trigger_condition="c")


def test_compute_trade_currencies_splits_give_and_get():
    options = [_option(cost_to_me="low"), _option(title="Expensive option", cost_to_me="high")]
    interests = [InterestItem(party="me", category="need", statement=_reviewed("Cash flow")), InterestItem(party="counterpart", category="need", statement=_reviewed("Their need"))]
    currencies = package_service.compute_trade_currencies(options, interests)

    give = [c for c in currencies if c.direction == "i_can_give"]
    get = [c for c in currencies if c.direction == "i_want_to_get"]
    assert len(give) == 1  # only the low-cost option
    assert len(get) == 1  # only my own interest, not the counterpart's


# --- SPEC §14.1 item 24: validator flags violates_redline for a redline-crossing package. ---
def test_validator_flags_violates_redline_for_crossing_package():
    redline = _redline("Cannot accept payment terms beyond 60 days")
    package = TradePackage(label="Aggressive package", option_ids=[], what_i_give=["Extend to 90 days"], what_i_get=["Full price"], equivalence_note="x")

    warnings = package_service.validate_against_limits(package, [redline], [])
    assert any("violates_redline" in w for w in warnings)


def test_validator_ignores_unconfirmed_redline():
    redline = _redline("Cannot accept payment terms beyond 60 days", confirmed=False)
    package = TradePackage(label="p", option_ids=[], what_i_give=["Extend to 90 days"], what_i_get=[], equivalence_note="x")
    assert package_service.validate_against_limits(package, [redline], []) == []


# --- Boundary-value table-driven test for crosses_bottomline. ---
@pytest.mark.parametrize(
    "direction,threshold,value,expect_cross",
    [
        ("min", "100000", "99999", True),
        ("min", "100000", "100000", False),
        ("min", "100000", "100001", False),
        ("max", "60", "61", True),
        ("max", "60", "60", False),
        ("max", "60", "59", False),
    ],
)
def test_validator_crosses_bottomline_boundary_values(direction, threshold, value, expect_cross):
    bottomline = _bottomline(direction, threshold)
    step = ConcessionStep(order=1, issue_id=None, from_value="irrelevant", to_value=value, ask_in_return="x", trigger_condition="y")
    warnings = package_service.validate_against_limits([step], [], [bottomline])
    assert any("crosses_bottomline" in w for w in warnings) == expect_cross


def test_validator_ignores_unconfirmed_bottomline():
    bottomline = _bottomline("min", "100000", confirmed=False)
    step = ConcessionStep(order=1, issue_id=None, from_value="x", to_value="1", ask_in_return="x", trigger_condition="y")
    assert package_service.validate_against_limits([step], [], [bottomline]) == []


# --- SPEC §14.1 item 26: an anchor without justification_standard fails validation. ---
def test_build_haggle_plan_raises_when_justification_standard_missing():
    draft = HagglePlanDraft(packages=[], anchor="$130k", justification_standard="   ", concession_ladder=[], counter_tactics=[])
    case = NegotiationCase()
    with pytest.raises(ValueError):
        package_service.build_haggle_plan(case, [], [], [], [], ai_client=_StubHaggleClient(draft))


# --- SPEC §14.1 item 25: ladder never crosses a confirmed bottomline; increments never grow. ---
def test_ladder_truncates_before_crossing_confirmed_bottomline():
    bottomline = _bottomline("min", "100000")
    draft = HagglePlanDraft(
        packages=[], anchor="$130k", justification_standard="Market rate",
        concession_ladder=[
            AIConcessionStepDraft(issue_id=None, from_value="130000", to_value="120000", ask_in_return="Net 15", trigger_condition="x"),
            AIConcessionStepDraft(issue_id=None, from_value="120000", to_value="90000", ask_in_return="Signed contract", trigger_condition="y"),
        ],
        counter_tactics=[],
    )
    case = NegotiationCase()
    plan = package_service.build_haggle_plan(case, [], [], [], [bottomline], ai_client=_StubHaggleClient(draft))

    assert len(plan.concession_ladder) == 1  # second step crosses the bottomline and is dropped
    assert all(step.ask_in_return for step in plan.concession_ladder)


def test_ladder_truncates_when_increments_grow():
    draft = HagglePlanDraft(
        packages=[], anchor="$130k", justification_standard="Market rate",
        concession_ladder=[
            AIConcessionStepDraft(issue_id=None, from_value="130000", to_value="125000", ask_in_return="Net 15", trigger_condition="x"),
            AIConcessionStepDraft(issue_id=None, from_value="125000", to_value="105000", ask_in_return="Signed contract", trigger_condition="y"),
        ],
        counter_tactics=[],
    )
    case = NegotiationCase()
    plan = package_service.build_haggle_plan(case, [], [], [], [], ai_client=_StubHaggleClient(draft))

    assert len(plan.concession_ladder) == 1  # 20000 decrement > first 5000 decrement -> dropped


def test_package_option_ids_filtered_to_known_options():
    option = _option()
    draft = HagglePlanDraft(
        packages=[AIPackageDraft(label="p", option_ids=[option.id, "hallucinated"], what_i_give=["x"], what_i_get=["y"], equivalence_note="z")],
        anchor="$130k", justification_standard="Market rate", concession_ladder=[], counter_tactics=[],
    )
    case = NegotiationCase()
    plan = package_service.build_haggle_plan(case, [option], [], [], [], ai_client=_StubHaggleClient(draft))

    assert plan.packages[0].option_ids == [option.id]
