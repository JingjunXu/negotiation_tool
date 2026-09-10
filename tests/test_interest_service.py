from negotiation_copilot import interest_service
from negotiation_copilot.ai_client import AIPositionLinkDraft, InterestRequest, PositionMapRequest
from negotiation_copilot.models import (
    DocumentRecord,
    Evidence,
    InterestItem,
    NegotiationCase,
    NegotiationIssue,
    ReviewedText,
)


def _doc(document_id: str, scope: str) -> DocumentRecord:
    return DocumentRecord(
        document_id=document_id, filename=f"{document_id}.txt", upload_index=0, file_type="txt",
        size_bytes=10, sha256="a" * 64, scope=scope, processing_status="processed",
    )


def _confidential_and_shared_case() -> NegotiationCase:
    confidential_role = ReviewedText(
        current_value="Vendor with a weak BATNA",
        ai_original_value="Vendor with a weak BATNA",
        evidence_status="explicit",
        evidence=[Evidence(document_id="confidential-doc", excerpt="internal note: our BATNA is weak")],
    )
    shared_context = ReviewedText(
        current_value="Annual renewal negotiation",
        ai_original_value="Annual renewal negotiation",
        evidence_status="explicit",
        evidence=[Evidence(document_id="shared-doc", excerpt="both parties agree this is a renewal")],
    )
    return NegotiationCase(
        documents=[_doc("confidential-doc", "my_confidential"), _doc("shared-doc", "shared")],
        my_role=confidential_role,
        context=shared_context,
    )


def test_counterpart_context_excludes_confidential_content():
    case = _confidential_and_shared_case()
    permitted = interest_service._permitted_document_ids(case, interest_service._PERMITTED_COUNTERPART_SCOPES)
    counterpart_context = interest_service.build_interest_context(case, allowed_document_ids=permitted)
    my_context = interest_service.build_interest_context(case, allowed_document_ids=None)

    assert "weak BATNA" not in counterpart_context
    assert "renewal negotiation" in counterpart_context
    assert "weak BATNA" in my_context  # unrestricted "me" context keeps everything


# Regression: build_interest_context previously omitted case.interests/case.targets
# entirely, so raw per-document-extracted interest signal never reached the
# actual interests-analysis stage even though it had been correctly extracted
# and stored — see docs/DECISIONS.md.
def test_raw_extracted_interests_and_targets_reach_the_context():
    case = _confidential_and_shared_case()
    case.interests = [
        ReviewedText(
            current_value="Tribal leader values the community's reliance on HfA's medical support",
            ai_original_value="Tribal leader values the community's reliance on HfA's medical support",
            evidence_status="explicit",
            evidence=[Evidence(document_id="shared-doc", excerpt="your community has come to rely on the essential medical support HfA provides")],
        )
    ]
    case.targets = [
        ReviewedText(
            current_value="Secure release of all nine surgeons",
            ai_original_value="Secure release of all nine surgeons",
            evidence_status="explicit",
            evidence=[Evidence(document_id="shared-doc", excerpt="nine surgeons were detained")],
        )
    ]

    my_context = interest_service.build_interest_context(case, allowed_document_ids=None)
    assert "community's reliance on HfA's medical support" in my_context
    assert "release of all nine surgeons" in my_context


def test_raw_extracted_interests_still_respect_confidential_filtering():
    case = _confidential_and_shared_case()
    case.interests = [
        ReviewedText(
            current_value="Internal-only interest note",
            ai_original_value="Internal-only interest note",
            evidence_status="explicit",
            evidence=[Evidence(document_id="confidential-doc", excerpt="internal only")],
        )
    ]
    permitted = interest_service._permitted_document_ids(case, interest_service._PERMITTED_COUNTERPART_SCOPES)
    counterpart_context = interest_service.build_interest_context(case, allowed_document_ids=permitted)
    my_context = interest_service.build_interest_context(case, allowed_document_ids=None)

    assert "Internal-only interest note" not in counterpart_context
    assert "Internal-only interest note" in my_context


class _StubInterestClient:
    def __init__(self, items: list[InterestItem]):
        self._items = items
        self.last_request: InterestRequest | None = None

    def analyze_interests(self, request: InterestRequest) -> list[InterestItem]:
        self.last_request = request
        return self._items


# --- SPEC §14.1 item 13: never a counterpart item with is_hypothesis=False. ---
def test_analyze_interests_forces_counterpart_hypothesis():
    case = _confidential_and_shared_case()
    sneaky_item = InterestItem(
        party="counterpart",
        category="fear",
        statement=ReviewedText(current_value="Fears bad precedent", ai_original_value="Fears bad precedent", evidence_status="inferred"),
        is_hypothesis=False,  # a misbehaving client trying to skip the hypothesis label
    )
    result = interest_service.analyze_interests(case, ai_client=_StubInterestClient([sneaky_item]))

    assert len(result) == 1
    assert result[0].is_hypothesis is True
    assert result[0].verification_question  # inferred + no question supplied -> service fills one in


# --- SPEC §14.1 item 14: counterpart interests derived only from shared/instructor_rules. ---
def test_counterpart_context_passed_to_client_excludes_confidential_scope():
    case = _confidential_and_shared_case()
    stub = _StubInterestClient([])
    interest_service.analyze_interests(case, ai_client=stub)

    assert "weak BATNA" not in stub.last_request.counterpart_context
    assert "renewal negotiation" in stub.last_request.counterpart_context
    assert "weak BATNA" in stub.last_request.my_context


def test_my_hard_constraints_forwarded_for_fake_client_relabeling():
    from negotiation_copilot.models import Constraint

    case = _confidential_and_shared_case()
    case.hard_constraints = [Constraint(statement=ReviewedText(current_value="Cannot exceed 60 days", ai_original_value="Cannot exceed 60 days", evidence_status="explicit"))]
    stub = _StubInterestClient([])
    interest_service.analyze_interests(case, ai_client=stub)

    assert stub.last_request.my_hard_constraints == case.hard_constraints


def _reviewed_simple(value: str) -> ReviewedText:
    return ReviewedText(current_value=value, ai_original_value=value, evidence_status="explicit", evidence=[])


class _StubPositionClient:
    def __init__(self, drafts: list[AIPositionLinkDraft]):
        self._drafts = drafts
        self.last_request: PositionMapRequest | None = None

    def map_positions_to_interests(self, request: PositionMapRequest) -> list[AIPositionLinkDraft]:
        self.last_request = request
        return self._drafts


def _case_with_issue_positions() -> NegotiationCase:
    issue = NegotiationIssue(
        title="Payment terms",
        my_position=_reviewed_simple("$120k in 30 days"),
        counterpart_position=_reviewed_simple("$100k in 60 days"),
    )
    return NegotiationCase(issues=[issue])


# --- SPEC §14.1: every underlying_interest_ids resolves to an existing InterestItem id. ---
def test_position_links_filter_out_unknown_interest_ids():
    case = _case_with_issue_positions()
    real_interest = InterestItem(party="me", category="need", statement=_reviewed_simple("Needs cash flow"))
    issue_id = case.issues[0].id

    drafts = [
        AIPositionLinkDraft(
            ref=f"issue:{issue_id}:me",
            underlying_interest_ids=[real_interest.id, "hallucinated-id-that-does-not-exist"],
            inference_basis="explicit",
            reframe_question="What would faster payment let you do?",
            misalignment_note=None,
        )
    ]
    links = interest_service.map_positions_to_interests(case, [real_interest], ai_client=_StubPositionClient(drafts))

    assert len(links) == 1
    assert links[0].underlying_interest_ids == [real_interest.id]


def test_position_links_use_service_data_for_party_and_statement_not_ai():
    case = _case_with_issue_positions()
    issue_id = case.issues[0].id
    drafts = [
        AIPositionLinkDraft(ref=f"issue:{issue_id}:me", underlying_interest_ids=[], inference_basis="x", reframe_question=None, misalignment_note="Doesn't serve my interests well"),
        AIPositionLinkDraft(ref=f"issue:{issue_id}:counterpart", underlying_interest_ids=[], inference_basis="x", reframe_question=None, misalignment_note="should be dropped for counterpart"),
    ]
    links = interest_service.map_positions_to_interests(case, [], ai_client=_StubPositionClient(drafts))

    me_link = next(l for l in links if l.party == "me")
    counterpart_link = next(l for l in links if l.party == "counterpart")
    assert me_link.stated_position.current_value == "$120k in 30 days"
    assert me_link.misalignment_note == "Doesn't serve my interests well"
    assert counterpart_link.stated_position.current_value == "$100k in 60 days"
    assert counterpart_link.misalignment_note is None  # SPEC: misalignment is a "my position" concept only


def test_position_links_ignore_unknown_refs_from_client():
    case = _case_with_issue_positions()
    drafts = [AIPositionLinkDraft(ref="issue:does-not-exist:me", underlying_interest_ids=[], inference_basis="x", reframe_question=None, misalignment_note=None)]
    links = interest_service.map_positions_to_interests(case, [], ai_client=_StubPositionClient(drafts))
    assert links == []


def test_no_positions_skips_client_call():
    case = NegotiationCase()

    class _ExplodingClient:
        def map_positions_to_interests(self, request):
            raise AssertionError("should not be called with zero positions")

    assert interest_service.map_positions_to_interests(case, [], ai_client=_ExplodingClient()) == []
