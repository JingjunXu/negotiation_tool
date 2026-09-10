from negotiation_copilot import option_service
from negotiation_copilot.ai_client import AIOptionDraft, OptionRequest
from negotiation_copilot.fake_clients import FakeAIClient
from negotiation_copilot.models import InterestItem, NegotiationCase, ReviewedText


def _reviewed(value: str) -> ReviewedText:
    return ReviewedText(current_value=value, ai_original_value=value, evidence_status="explicit", evidence=[])


def _interest(party: str) -> InterestItem:
    return InterestItem(party=party, category="need", statement=_reviewed(f"{party} needs something"))


class _StubOptionClient:
    def __init__(self, drafts: list[AIOptionDraft]):
        self._drafts = drafts
        self.last_request: OptionRequest | None = None

    def generate_options(self, request: OptionRequest) -> list[AIOptionDraft]:
        self.last_request = request
        return self._drafts


def _draft(**overrides) -> AIOptionDraft:
    defaults = dict(
        title="Staged payments", description="Split into milestones.", option_type="time",
        serves_my_interest_ids=[], serves_their_interest_ids=[],
        cost_to_me="low", value_to_them_hypothesis="medium", depends_on=[], evidence_status="inferred",
    )
    defaults.update(overrides)
    return AIOptionDraft(**defaults)


# --- SPEC §14.1 item 23: every generated option references an existing interest id. ---
def test_option_serving_no_known_interest_is_dropped():
    case = NegotiationCase()
    interest = _interest("me")
    draft = _draft(serves_my_interest_ids=["hallucinated-id"], serves_their_interest_ids=[])
    options = option_service.generate_options(case, [interest], ai_client=_StubOptionClient([draft]))
    assert options == []


def test_option_with_valid_interest_id_is_kept_and_filtered():
    case = NegotiationCase()
    interest = _interest("me")
    draft = _draft(serves_my_interest_ids=[interest.id, "hallucinated-id"])
    [option] = option_service.generate_options(case, [interest], ai_client=_StubOptionClient([draft]))
    assert option.serves_my_interest_ids == [interest.id]


# --- SPEC §14.1 item 22: option generation never sets status="rejected" itself. ---
def test_options_always_start_as_idea():
    case = NegotiationCase()
    interest = _interest("me")
    draft = _draft(serves_my_interest_ids=[interest.id])
    [option] = option_service.generate_options(case, [interest], ai_client=_StubOptionClient([draft]))
    assert option.status == "idea"


def test_generate_more_options_returns_only_new_ones_for_caller_to_append():
    case = NegotiationCase()
    interest = _interest("me")
    from negotiation_copilot.models import NegotiationOption

    existing = NegotiationOption(
        title="Existing option", description="x", option_type="time", serves_my_interest_ids=[interest.id],
        serves_their_interest_ids=[], cost_to_me="low", value_to_them_hypothesis="low", evidence_status="inferred",
    )
    draft = _draft(title="Brand new option", serves_my_interest_ids=[interest.id])
    stub = _StubOptionClient([draft])
    new_options = option_service.generate_options(case, [interest], ai_client=stub, existing_options=[existing])

    assert len(new_options) == 1
    assert new_options[0].title == "Brand new option"
    assert stub.last_request.existing_option_titles == ["Existing option"]


# --- SPEC §14.1 item 22: >= 8 options spanning >= 4 types on a normal fixture. ---
def test_fake_client_generates_breadth_on_normal_case():
    case = NegotiationCase()
    interests = [_interest("me"), _interest("counterpart")]
    options = option_service.generate_options(case, interests, ai_client=FakeAIClient())

    assert len(options) >= 8
    assert len({o.option_type for o in options}) >= 4
    for option in options:
        assert option.serves_my_interest_ids or option.serves_their_interest_ids
        assert option.status == "idea"


def test_fake_client_returns_nothing_without_any_known_interests():
    case = NegotiationCase()
    assert option_service.generate_options(case, [], ai_client=FakeAIClient()) == []
