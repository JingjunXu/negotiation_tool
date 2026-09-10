from negotiation_copilot import agreement_service
from negotiation_copilot.ai_client import AgreementRequest, AIAgreementItemDraft
from negotiation_copilot.models import Conflict, ConflictingValue, DocumentRecord, Evidence, NegotiationCase


def _doc(document_id: str, scope: str) -> DocumentRecord:
    return DocumentRecord(
        document_id=document_id, filename=f"{document_id}.txt", upload_index=0, file_type="txt",
        size_bytes=10, sha256="a" * 64, scope=scope, processing_status="processed",
    )


class _StubAgreementClient:
    def __init__(self, drafts: list[AIAgreementItemDraft]):
        self._drafts = drafts
        self.last_request: AgreementRequest | None = None

    def map_agreement_landscape(self, request: AgreementRequest) -> list[AIAgreementItemDraft]:
        self.last_request = request
        return self._drafts


# --- SPEC §14.1 item 16: a one-sided assertion is never classified shared. ---
def test_shared_claim_with_only_confidential_evidence_is_downgraded():
    case = NegotiationCase(documents=[_doc("confidential-doc", "my_confidential")])
    draft = AIAgreementItemDraft(
        kind="fact", statement="We started in March", standing="shared",
        my_view="March", counterpart_view=None, conflict_id=None, verification_question=None,
        evidence=[Evidence(document_id="confidential-doc", excerpt="we started in March")],
    )
    items = agreement_service.analyze_agreement_landscape(case, ai_client=_StubAgreementClient([draft]))

    assert len(items) == 1
    assert items[0].standing == "unverified"
    assert items[0].verification_question  # downgraded items must carry one


def test_shared_claim_with_shared_scope_evidence_stays_shared():
    case = NegotiationCase(documents=[_doc("shared-doc", "shared")])
    draft = AIAgreementItemDraft(
        kind="fact", statement="We started in March", standing="shared",
        my_view="March", counterpart_view="March", conflict_id=None, verification_question=None,
        evidence=[Evidence(document_id="shared-doc", excerpt="both agree we started in March")],
    )
    items = agreement_service.analyze_agreement_landscape(case, ai_client=_StubAgreementClient([draft]))

    assert items[0].standing == "shared"
    assert items[0].verification_question is None


# --- SPEC §14.1 item 15: every contested/unverified item carries a verification question. ---
def test_contested_item_without_question_gets_one_synthesized():
    case = NegotiationCase()
    draft = AIAgreementItemDraft(
        kind="fact", statement="Deadline date", standing="contested",
        my_view="March 1", counterpart_view="April 1", conflict_id=None, verification_question=None,
        evidence=[],
    )
    items = agreement_service.analyze_agreement_landscape(case, ai_client=_StubAgreementClient([draft]))
    assert items[0].verification_question


# --- SPEC §14.1 item 17: contested numeric items link an existing conflict_id, never a fabricated one. ---
def test_valid_conflict_id_is_preserved():
    conflict = Conflict(field_description="Deadline date", values=[ConflictingValue(document_id="doc-a", value="March 1", evidence=Evidence(document_id="doc-a", excerpt="March 1"))])
    case = NegotiationCase(conflicts=[conflict])
    draft = AIAgreementItemDraft(
        kind="fact", statement="Deadline date", standing="contested", my_view=None, counterpart_view=None,
        conflict_id=conflict.id, verification_question="Which deadline is correct?", evidence=[],
    )
    items = agreement_service.analyze_agreement_landscape(case, ai_client=_StubAgreementClient([draft]))
    assert items[0].conflict_id == conflict.id


def test_hallucinated_conflict_id_is_dropped():
    case = NegotiationCase(conflicts=[])
    draft = AIAgreementItemDraft(
        kind="fact", statement="Deadline date", standing="contested", my_view=None, counterpart_view=None,
        conflict_id="does-not-exist", verification_question="Which deadline is correct?", evidence=[],
    )
    items = agreement_service.analyze_agreement_landscape(case, ai_client=_StubAgreementClient([draft]))
    assert items[0].conflict_id is None
