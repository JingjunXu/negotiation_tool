from negotiation_copilot import consolidation_service as cs
from negotiation_copilot.ai_client import ConsolidationPlan, ConsolidationRequest, IssueGroupDraft
from negotiation_copilot.fake_clients import FakeAIClient
from negotiation_copilot.models import (
    DocumentExtraction,
    DocumentRecord,
    DocumentSummary,
    Evidence,
    NegotiationIssue,
    ReviewedText,
)


def _doc(document_id: str, upload_index: int) -> DocumentRecord:
    return DocumentRecord(
        document_id=document_id, filename=f"{document_id}.txt", upload_index=upload_index, file_type="txt",
        size_bytes=10, sha256="a" * 64, scope="shared", processing_status="processed",
    )


def _reviewed(value: str, document_id: str, status: str = "explicit") -> ReviewedText:
    ev = Evidence(document_id=document_id, excerpt=value)
    return ReviewedText(current_value=value, ai_original_value=value, evidence_status=status, evidence=[ev])


class _StubConsolidateClient:
    def __init__(self, plan: ConsolidationPlan):
        self._plan = plan

    def consolidate_case(self, request: ConsolidationRequest) -> ConsolidationPlan:
        return self._plan


# --- SPEC §14.1 item 9: merged issues keep all evidence. ---
def test_merged_issue_keeps_evidence_from_both_documents():
    issue_a = NegotiationIssue(title="Payment terms", evidence=[Evidence(document_id="doc-a", excerpt="30 day terms")])
    issue_b = NegotiationIssue(title="Payment window", evidence=[Evidence(document_id="doc-b", excerpt="pay within a month")])
    extraction_a = DocumentExtraction(document_id="doc-a", summary=DocumentSummary(bullets=[]), issues=[issue_a])
    extraction_b = DocumentExtraction(document_id="doc-b", summary=DocumentSummary(bullets=[]), issues=[issue_b])

    plan = ConsolidationPlan(
        issue_groups=[
            IssueGroupDraft(issue_refs=[f"doc-a:{issue_a.id}", f"doc-b:{issue_b.id}"], merged_title="Payment terms")
        ]
    )
    case = cs.consolidate_case(
        [_doc("doc-a", 0), _doc("doc-b", 1)], None, [extraction_a, extraction_b],
        ai_client=_StubConsolidateClient(plan),
    )

    assert len(case.issues) == 1
    merged = case.issues[0]
    assert merged.title == "Payment terms"
    excerpts = {e.excerpt for e in merged.evidence}
    assert excerpts == {"30 day terms", "pay within a month"}


# --- SPEC §14.1 item 10: divergent numbers create conflicts instead of silent overwrites. ---
def test_divergent_targets_create_conflict_not_silent_overwrite():
    issue_a = NegotiationIssue(title="Price", target=_reviewed("$120k", "doc-a"))
    issue_b = NegotiationIssue(title="Price", target=_reviewed("$150k", "doc-b"))
    extraction_a = DocumentExtraction(document_id="doc-a", summary=DocumentSummary(bullets=[]), issues=[issue_a])
    extraction_b = DocumentExtraction(document_id="doc-b", summary=DocumentSummary(bullets=[]), issues=[issue_b])

    plan = ConsolidationPlan(
        issue_groups=[IssueGroupDraft(issue_refs=[f"doc-a:{issue_a.id}", f"doc-b:{issue_b.id}"], merged_title="Price")]
    )
    case = cs.consolidate_case(
        [_doc("doc-a", 0), _doc("doc-b", 1)], None, [extraction_a, extraction_b],
        ai_client=_StubConsolidateClient(plan),
    )

    assert len(case.conflicts) == 1
    conflict = case.conflicts[0]
    values = {v.value for v in conflict.values}
    assert values == {"$120k", "$150k"}
    # Not silently overwritten: the merged issue keeps *a* value, and the conflict is visible.
    assert case.issues[0].target.current_value in {"$120k", "$150k"}


def test_identical_targets_merge_evidence_without_conflict():
    issue_a = NegotiationIssue(title="Price", target=_reviewed("$120k", "doc-a"))
    issue_b = NegotiationIssue(title="Price", target=_reviewed("$120k", "doc-b"))
    extraction_a = DocumentExtraction(document_id="doc-a", summary=DocumentSummary(bullets=[]), issues=[issue_a])
    extraction_b = DocumentExtraction(document_id="doc-b", summary=DocumentSummary(bullets=[]), issues=[issue_b])

    plan = ConsolidationPlan(
        issue_groups=[IssueGroupDraft(issue_refs=[f"doc-a:{issue_a.id}", f"doc-b:{issue_b.id}"], merged_title="Price")]
    )
    case = cs.consolidate_case(
        [_doc("doc-a", 0), _doc("doc-b", 1)], None, [extraction_a, extraction_b],
        ai_client=_StubConsolidateClient(plan),
    )

    assert case.conflicts == []
    assert len(case.issues[0].target.evidence) == 2


# --- SPEC §14.1 item 11: (consolidation must never corrupt) ai_original_value. ---
def test_single_source_value_passes_through_unchanged_preserving_ai_original_value():
    original = _reviewed("Vendor negotiating renewal", "doc-a", status="inferred")
    extraction = DocumentExtraction(document_id="doc-a", summary=DocumentSummary(bullets=[]), my_role=original)

    case = cs.consolidate_case(
        [_doc("doc-a", 0)], None, [extraction],
        ai_client=_StubConsolidateClient(ConsolidationPlan(issue_groups=[])),
    )

    assert case.my_role is original  # identity preserved, not just equality
    assert case.my_role.ai_original_value == "Vendor negotiating renewal"


def test_ungrouped_issues_pass_through():
    issue = NegotiationIssue(title="Unrelated issue", evidence=[Evidence(document_id="doc-a", excerpt="x")])
    extraction = DocumentExtraction(document_id="doc-a", summary=DocumentSummary(bullets=[]), issues=[issue])

    case = cs.consolidate_case(
        [_doc("doc-a", 0)], None, [extraction],
        ai_client=_StubConsolidateClient(ConsolidationPlan(issue_groups=[])),
    )

    assert len(case.issues) == 1
    assert case.issues[0].title == "Unrelated issue"


def test_consolidate_with_fake_client_end_to_end():
    issue_a = NegotiationIssue(title="Payment Terms", evidence=[Evidence(document_id="doc-a", excerpt="x")])
    issue_b = NegotiationIssue(title="payment terms!", evidence=[Evidence(document_id="doc-b", excerpt="y")])
    extraction_a = DocumentExtraction(document_id="doc-a", summary=DocumentSummary(bullets=[]), issues=[issue_a])
    extraction_b = DocumentExtraction(document_id="doc-b", summary=DocumentSummary(bullets=[]), issues=[issue_b])

    case = cs.consolidate_case(
        [_doc("doc-a", 0), _doc("doc-b", 1)], None, [extraction_a, extraction_b],
        ai_client=FakeAIClient(),
    )

    assert len(case.issues) == 1  # normalized-title match merges them
    excerpts = {e.excerpt for e in case.issues[0].evidence}
    assert excerpts == {"x", "y"}
