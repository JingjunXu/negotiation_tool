from streamlit.testing.v1 import AppTest

from negotiation_copilot.fixtures import sample_case
from negotiation_copilot.models import DocumentGroup, DocumentRecord, MaterialOrganizationResult

PAGE_SCRIPT = "from negotiation_copilot.pages import pipeline\npipeline.render()\n"


def test_thematic_grouping_can_be_accepted():
    case = sample_case()
    assert case.organization.organization_mode == "thematic"
    assert case.organization.review_status == "unreviewed"

    at = AppTest.from_string(PAGE_SCRIPT)
    at.session_state["case"] = case
    at.run(timeout=15)
    assert not at.exception

    # There is exactly one button on the thematic path: "Accept this grouping".
    assert len(at.button) == 1
    at.button[0].click().run(timeout=15)
    assert not at.exception
    assert at.session_state["case"].organization.review_status == "confirmed"


def _temporal_case():
    case = sample_case()
    case.documents = [
        DocumentRecord(
            document_id="doc-a", filename="b_second.txt", upload_index=0, file_type="txt",
            size_bytes=10, sha256="a" * 64, scope="shared", processing_status="processed",
        ),
        DocumentRecord(
            document_id="doc-b", filename="a_first.txt", upload_index=1, file_type="txt",
            size_bytes=10, sha256="b" * 64, scope="shared", processing_status="processed",
        ),
    ]
    case.organization = MaterialOrganizationResult(
        organization_mode="chronological",
        temporal_order_applicable=True,
        proposed_order=["doc-a", "doc-b"],
        confirmed_order=None,
        groups=[],
        relations=[],
        confidence="high",
        rationale="doc-a is dated before doc-b in body text.",
        unresolved_ambiguities=[],
        review_status="unreviewed",
    )
    return case


def test_temporal_order_comparison_shows_all_three_and_accepts_ai_order():
    case = _temporal_case()
    at = AppTest.from_string(PAGE_SCRIPT)
    at.session_state["case"] = case
    at.run(timeout=15)
    assert not at.exception

    radio = at.radio(key="org_order_choice")
    assert radio.value == "AI proposed order"

    at.button[0].click().run(timeout=15)
    assert not at.exception

    updated = at.session_state["case"].organization
    assert updated.confirmed_order == ["doc-a", "doc-b"]
    assert updated.review_status == "confirmed"


def test_temporal_order_choosing_upload_order_marks_edited_by_user():
    case = _temporal_case()
    at = AppTest.from_string(PAGE_SCRIPT)
    at.session_state["case"] = case
    at.run(timeout=15)

    at.radio(key="org_order_choice").set_value("Upload order").run(timeout=15)
    at.button[0].click().run(timeout=15)

    updated = at.session_state["case"].organization
    assert updated.confirmed_order == ["doc-a", "doc-b"]  # upload order happens to match here
    # Force a genuinely different chosen order to check the "edited_by_user" label
    at2 = AppTest.from_string(PAGE_SCRIPT)
    case2 = _temporal_case()
    case2.documents[0].upload_index, case2.documents[1].upload_index = 1, 0  # flip upload order vs AI order
    at2.session_state["case"] = case2
    at2.run(timeout=15)
    at2.radio(key="org_order_choice").set_value("Upload order").run(timeout=15)
    at2.button[0].click().run(timeout=15)
    updated2 = at2.session_state["case"].organization
    assert updated2.confirmed_order == ["doc-b", "doc-a"]
    assert updated2.review_status == "edited_by_user"
