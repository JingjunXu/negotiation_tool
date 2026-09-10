"""Material relationship judgment (SPEC §6): per-document cues (phase A,
T3.1) and cross-document organization (phase B, added in T3.2).
"""

from .ai_client import AIClient, DocumentMeta, MaterialOrganizationRequest, RelationshipCueRequest
from .models import MaterialOrganizationResult, ParagraphRecord, PDFPageResult, RelationshipCue, TextUnit


def text_units_from_paragraphs(paragraphs: list[ParagraphRecord]) -> list[TextUnit]:
    return [TextUnit(document_id=p.document_id, paragraph_id=p.paragraph_id, text=p.text) for p in paragraphs]


def text_units_from_pdf_pages(pages: list[PDFPageResult]) -> list[TextUnit]:
    return [
        TextUnit(document_id=page.document_id, page_number=page.page_number, text=page.content)
        for page in pages
        if page.status != "failed"
    ]


def extract_relationship_cues(
    document_id: str,
    filename: str,
    units: list[TextUnit],
    *,
    ai_client: AIClient,
) -> list[RelationshipCue]:
    """Per-document cue extraction (SPEC §6.2 phase A)."""
    if not units:
        return []
    return ai_client.extract_relationship_cues(
        RelationshipCueRequest(document_id=document_id, filename=filename, units=units)
    )


def organize_materials(
    documents: list[DocumentMeta],
    cues: list[RelationshipCue],
    *,
    ai_client: AIClient,
) -> MaterialOrganizationResult:
    """Cross-document organization (SPEC §6.2 phase B)."""
    result = ai_client.organize_materials(MaterialOrganizationRequest(documents=documents, cues=cues))
    # Defensive: organization is never auto-confirmed by AI (SPEC §6.3 — the
    # user accepts, edits, or disables the proposal), regardless of what any
    # AIClient implementation returns.
    return result.model_copy(update={"confirmed_order": None, "review_status": "unreviewed"})
