from negotiation_copilot import material_organization_service as mos
from negotiation_copilot.ai_client import DocumentMeta, MaterialOrganizationRequest, RelationshipCueRequest
from negotiation_copilot.fake_clients import FakeAIClient
from negotiation_copilot.models import MaterialOrganizationResult, ParagraphRecord, PDFPageResult, RelationshipCue


def test_text_units_from_paragraphs():
    paragraphs = [
        ParagraphRecord(document_id="doc-1", paragraph_id="para-1", index=0, text="First."),
        ParagraphRecord(document_id="doc-1", paragraph_id="para-2", index=1, text="Second."),
    ]
    units = mos.text_units_from_paragraphs(paragraphs)
    assert [u.text for u in units] == ["First.", "Second."]
    assert all(u.page_number is None for u in units)
    assert [u.paragraph_id for u in units] == ["para-1", "para-2"]


def test_text_units_from_pdf_pages_skips_failed_pages():
    pages = [
        PDFPageResult(document_id="doc-1", page_number=1, reading_method="native_text", content="Page one", status="success"),
        PDFPageResult(document_id="doc-1", page_number=2, reading_method="native_text", content="", status="failed", error_type="unreadable"),
    ]
    units = mos.text_units_from_pdf_pages(pages)
    assert len(units) == 1
    assert units[0].page_number == 1
    assert units[0].paragraph_id is None


class _StubAIClient:
    def __init__(self, cues: list[RelationshipCue]):
        self._cues = cues
        self.last_request: RelationshipCueRequest | None = None

    def extract_relationship_cues(self, request: RelationshipCueRequest) -> list[RelationshipCue]:
        self.last_request = request
        return self._cues


def test_extract_relationship_cues_delegates_to_client():
    units = mos.text_units_from_paragraphs(
        [ParagraphRecord(document_id="doc-1", paragraph_id="para-1", index=0, text="Draft agreement, dated March 3, 2025.")]
    )
    expected = [
        RelationshipCue(document_id="doc-1", cue_type="date", normalized_value="March 3, 2025", excerpt="dated March 3, 2025", paragraph_id="para-1")
    ]
    stub = _StubAIClient(expected)

    result = mos.extract_relationship_cues("doc-1", "brief.txt", units, ai_client=stub)

    assert result == expected
    assert stub.last_request.document_id == "doc-1"
    assert stub.last_request.filename == "brief.txt"


def test_extract_relationship_cues_returns_empty_for_no_units():
    class _ExplodingClient:
        def extract_relationship_cues(self, request):
            raise AssertionError("should not be called with zero units")

    assert mos.extract_relationship_cues("doc-1", "empty.txt", [], ai_client=_ExplodingClient()) == []


def _date_cue(doc_id: str, date_text: str) -> RelationshipCue:
    return RelationshipCue(document_id=doc_id, cue_type="date", normalized_value=date_text, excerpt=f"dated {date_text}")


def _version_cue(doc_id: str, marker: str) -> RelationshipCue:
    return RelationshipCue(document_id=doc_id, cue_type="version", normalized_value=marker, excerpt=marker)


def _role_cue(doc_id: str, role: str) -> RelationshipCue:
    return RelationshipCue(document_id=doc_id, cue_type="document_role", normalized_value=role, excerpt=role)


class _StubOrgClient:
    def __init__(self, result: MaterialOrganizationResult):
        self._result = result

    def organize_materials(self, request: MaterialOrganizationRequest) -> MaterialOrganizationResult:
        return self._result


def test_organize_materials_never_auto_confirms_even_if_client_tries_to(tmp_path):
    sneaky_result = MaterialOrganizationResult(
        organization_mode="chronological", temporal_order_applicable=True,
        proposed_order=["a", "b"], confirmed_order=["a", "b"], confidence="high",
        review_status="confirmed",
    )
    docs = [DocumentMeta(document_id="a", filename="a.txt", upload_index=0)]
    result = mos.organize_materials(docs, [], ai_client=_StubOrgClient(sneaky_result))
    assert result.confirmed_order is None
    assert result.review_status == "unreviewed"


# --- SPEC §14.1 item 5: genuinely temporal materials with misleading filenames
# are ordered by body text, never by filename. ---
def test_temporal_materials_ordered_by_body_text_despite_misleading_filenames():
    docs = [
        DocumentMeta(document_id="doc-03", filename="03_appears_last.txt", upload_index=0),
        DocumentMeta(document_id="doc-01", filename="01_appears_first.txt", upload_index=1),
        DocumentMeta(document_id="doc-02", filename="02_appears_middle.txt", upload_index=2),
    ]
    # Filenames imply order doc-01, doc-02, doc-03 — the opposite of the truth.
    cues = [
        _date_cue("doc-03", "January 1, 2024"),   # actually earliest
        _date_cue("doc-01", "February 1, 2024"),  # actually middle
        _date_cue("doc-02", "March 1, 2024"),     # actually latest
    ]
    request = MaterialOrganizationRequest(documents=docs, cues=cues)
    result = FakeAIClient().organize_materials(request)

    assert result.organization_mode == "chronological"
    assert result.temporal_order_applicable is True
    assert result.proposed_order == ["doc-03", "doc-01", "doc-02"]


# --- SPEC §14.1 item 6: non-temporal materials are classified
# thematic/complementary/independent, not forced into an order. ---
def test_non_temporal_materials_grouped_thematically_not_forced_into_order():
    docs = [
        DocumentMeta(document_id="doc-1", filename="minutes.txt", upload_index=0),
        DocumentMeta(document_id="doc-2", filename="report.txt", upload_index=1),
    ]
    cues = [_role_cue("doc-1", "meeting minutes"), _role_cue("doc-2", "meeting minutes")]
    result = FakeAIClient().organize_materials(MaterialOrganizationRequest(documents=docs, cues=cues))

    assert result.organization_mode in {"thematic", "complementary", "independent"}
    assert result.temporal_order_applicable is False
    assert result.proposed_order is None


# --- SPEC §14.1 item 7: mixed mode orders only the temporal subset. ---
def test_mixed_mode_orders_only_the_temporal_subset():
    docs = [
        DocumentMeta(document_id="dated-1", filename="a.txt", upload_index=0),
        DocumentMeta(document_id="dated-2", filename="b.txt", upload_index=1),
        DocumentMeta(document_id="undated-1", filename="c.txt", upload_index=2),
        DocumentMeta(document_id="undated-2", filename="d.txt", upload_index=3),
    ]
    cues = [_date_cue("dated-1", "January 1, 2024"), _date_cue("dated-2", "February 1, 2024")]
    result = FakeAIClient().organize_materials(MaterialOrganizationRequest(documents=docs, cues=cues))

    assert result.organization_mode == "mixed"
    assert result.temporal_order_applicable is True
    assert result.proposed_order == ["dated-1", "dated-2"]
    assert "undated-1" not in result.proposed_order
    assert "undated-2" not in result.proposed_order
    ungrouped = {doc_id for group in result.groups for doc_id in group.document_ids}
    assert {"undated-1", "undated-2"} <= ungrouped


# --- SPEC §14.1 item 8: low-confidence organization is never auto-confirmed
# and must require user confirmation. ---
def test_low_confidence_organization_stays_unreviewed():
    docs = [
        DocumentMeta(document_id="dated-1", filename="a.txt", upload_index=0),
        DocumentMeta(document_id="undated-1", filename="b.txt", upload_index=1),
        DocumentMeta(document_id="undated-2", filename="c.txt", upload_index=2),
        DocumentMeta(document_id="undated-3", filename="d.txt", upload_index=3),
    ]
    # Only one of four documents has any temporal evidence — a weak basis for "mixed".
    cues = [_date_cue("dated-1", "January 1, 2024")]
    result = FakeAIClient().organize_materials(MaterialOrganizationRequest(documents=docs, cues=cues))

    assert result.review_status == "unreviewed"
    assert result.confirmed_order is None
    # A single dated document out of four is not a confident temporal signal.
    if result.temporal_order_applicable:
        assert result.confidence == "low"


def test_versioned_mode_orders_draft_before_final():
    docs = [
        DocumentMeta(document_id="doc-a", filename="a.txt", upload_index=0),
        DocumentMeta(document_id="doc-b", filename="b.txt", upload_index=1),
    ]
    cues = [_version_cue("doc-b", "final"), _version_cue("doc-a", "draft")]
    result = FakeAIClient().organize_materials(MaterialOrganizationRequest(documents=docs, cues=cues))

    assert result.organization_mode == "versioned"
    assert result.proposed_order == ["doc-a", "doc-b"]


def test_independent_mode_when_no_evidence_connects_documents():
    docs = [
        DocumentMeta(document_id="doc-a", filename="a.txt", upload_index=0),
        DocumentMeta(document_id="doc-b", filename="b.txt", upload_index=1),
    ]
    result = FakeAIClient().organize_materials(MaterialOrganizationRequest(documents=docs, cues=[]))

    assert result.organization_mode == "independent"
    assert result.temporal_order_applicable is False
    assert result.proposed_order is None
