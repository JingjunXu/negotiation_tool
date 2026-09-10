"""T8.2: a fake end-to-end run over a small fixture set (SPEC §14.2),
chaining every real pipeline stage together. This is deliberately different
from the per-service unit tests elsewhere: those construct hand-built
inputs for one stage in isolation; this test feeds each stage's *real*
output into the next, which is the only way to catch a wiring mistake
(wrong field name, wrong shape) that unit tests using hand-built fixtures
would never see.

Materials, matching SPEC §14.2's list at a workable scale:
- a shared "case" document (TXT) — context both sides can see
- a my_confidential "private brief" (TXT) — my role, a hard constraint,
  an issue with a deadline that conflicts with the shared document
- an instructor_rules document (TXT)

Fake mode's per-document extraction is deliberately thin (it never guesses
semantic fields like objective/issues — see docs/DECISIONS.md T3.4), so
this test enriches the case once after consolidation to simulate the user
confirming fields via the Negotiation Map UI (SPEC's "user review fixture"
step) — otherwise the analysis layer would have nothing to work with,
which is expected behavior, not a bug, but not useful for exercising the
rest of the chain.
"""

from pathlib import Path

from negotiation_copilot import (
    agreement_service,
    brief_service,
    consolidation_service,
    constraint_service,
    document_parser,
    extraction_service,
    interest_service,
    language_service,
    material_organization_service as mos,
    note_service,
    option_service,
    package_service,
    walkaway_service,
)
from negotiation_copilot.ai_client import DocumentMeta
from negotiation_copilot.config import Config
from negotiation_copilot.fake_clients import FakeAIClient
from negotiation_copilot.models import (
    DocumentRecord,
    LanguageDraftRequest,
    NegotiationAnalysis,
    NegotiationCase,
    NegotiationIssue,
    ReviewedText,
)

SHARED_DOC = (
    b"This is the shared case summary agreed by both sides.\n\n"
    b"Both parties accept that the contract review period ends March 1, 2025.\n\n"
    b"Both parties value a fast, low-friction resolution to this matter."
)

CONFIDENTIAL_DOC = (
    b"Internal role brief: I am the vendor's negotiator for this renewal.\n\n"
    b"Cannot accept payment terms beyond 60 days per company policy.\n\n"
    b"Internal note: the review period actually closes April 1, 2025, not March 1."
)

INSTRUCTOR_DOC = b"Simulation instructor rules: all offers must be submitted in writing."


def _config(tmp_path: Path) -> Config:
    return Config(
        openai_api_key=None, openai_model=None, openai_store_responses=False, run_live_openai_tests=False,
        app_data_dir=tmp_path, max_upload_mb=25, max_pdf_pages=50, log_level="INFO",
    )


def _reviewed(value: str) -> ReviewedText:
    return ReviewedText(current_value=value, ai_original_value=value, evidence_status="explicit", evidence=[])


def test_fake_end_to_end_pipeline(tmp_path):
    ai_client = FakeAIClient()
    cfg = _config(tmp_path)

    # --- 1. Materials: three documents across all three scopes. ---
    documents = [
        DocumentRecord(
            document_id="doc-shared", filename="shared_case.txt", upload_index=0, file_type="txt",
            size_bytes=len(SHARED_DOC), sha256=document_parser.sha256_of(SHARED_DOC), scope="shared", processing_status="processed",
        ),
        DocumentRecord(
            document_id="doc-confidential", filename="private_brief.txt", upload_index=1, file_type="txt",
            size_bytes=len(CONFIDENTIAL_DOC), sha256=document_parser.sha256_of(CONFIDENTIAL_DOC), scope="my_confidential", processing_status="processed",
        ),
        DocumentRecord(
            document_id="doc-instructor", filename="instructor_rules.txt", upload_index=2, file_type="txt",
            size_bytes=len(INSTRUCTOR_DOC), sha256=document_parser.sha256_of(INSTRUCTOR_DOC), scope="instructor_rules", processing_status="processed",
        ),
    ]
    raw_bytes = {
        "doc-shared": SHARED_DOC,
        "doc-confidential": CONFIDENTIAL_DOC,
        "doc-instructor": INSTRUCTOR_DOC,
    }

    # --- 2. Parse + relationship cues + organization. ---
    all_cues = []
    all_extractions = []
    for doc in documents:
        paragraphs = document_parser.parse_document(doc.document_id, raw_bytes[doc.document_id], "txt", app_data_dir=tmp_path)
        assert paragraphs  # ingestion actually produced content

        units = mos.text_units_from_paragraphs(paragraphs)
        cues = mos.extract_relationship_cues(doc.document_id, doc.filename, units, ai_client=ai_client)
        all_cues.extend(cues)

        extraction = extraction_service.extract_document(doc.document_id, doc.filename, units, ai_client=ai_client)
        all_extractions.append(extraction)

    doc_metas = [DocumentMeta(document_id=d.document_id, filename=d.filename, upload_index=d.upload_index) for d in documents]
    organization = mos.organize_materials(doc_metas, all_cues, ai_client=ai_client)
    assert organization.review_status == "unreviewed"  # never auto-confirmed

    # --- 3. Consolidation. ---
    case = consolidation_service.consolidate_case(documents, organization, all_extractions, ai_client=ai_client)
    case.relationship_cues = all_cues
    assert case.document_extractions == all_extractions

    # --- 4. Simulate the user confirming fields via the Negotiation Map UI
    # (SPEC's "user review fixture" step) — fake extraction is deliberately
    # thin, so this is what makes the rest of the chain meaningful. ---
    case.my_role = _reviewed("Vendor's negotiator")
    case.counterpart_role = _reviewed("Client procurement lead")
    case.objective = _reviewed("Secure contract renewal on acceptable terms")
    case.issues = [
        NegotiationIssue(title="Review period deadline", target=_reviewed("March 1, 2025"), priority="high", flexibility="firm")
    ]
    case.targets = [_reviewed("$130,000")]

    # --- 5. Analysis layer, in SPEC order. ---
    interests = interest_service.analyze_interests(case, ai_client=ai_client)
    position_links = interest_service.map_positions_to_interests(case, interests, ai_client=ai_client)
    agreement_landscape = agreement_service.analyze_agreement_landscape(case, ai_client=ai_client)
    walk_away, gap_warnings = walkaway_service.analyze_walk_away(case, ai_client=ai_client)
    case.warnings.extend(gap_warnings)
    redlines, bottomlines = constraint_service.classify_constraints(case, walk_away, ai_client=ai_client)

    case.analysis = case.analysis or NegotiationAnalysis()
    case.analysis.interests = interests
    case.analysis.position_links = position_links
    case.analysis.agreement_landscape = agreement_landscape
    case.analysis.walk_away = walk_away
    case.analysis.redlines = redlines
    case.analysis.bottomlines = bottomlines

    options = option_service.generate_options(case, interests, ai_client=ai_client)
    case.analysis.options = options
    assert all(o.status == "idea" for o in options)  # never auto-rejected or auto-viable

    haggle_plan = package_service.build_haggle_plan(case, options, interests, redlines, bottomlines, ai_client=ai_client)
    case.analysis.haggle_plan = haggle_plan

    # --- 6. Prep Brief + Live Card. ---
    brief = brief_service.generate_brief(case, ai_client=ai_client)
    assert len(brief.sections) == 18
    live_card = brief_service.build_live_card(case, brief)
    assert len(live_card.my_top_interests) <= 3

    # --- 7. Section judgment and note. ---
    objective_section = next(s for s in brief.sections if s.section_id == "objective_success_criteria")
    note_service.add_note(case.case_id, objective_section, "my_judgment", "This framing looks right.", app_data_dir=tmp_path)
    note_service.set_status(case.case_id, objective_section, "confirmed", app_data_dir=tmp_path)
    assert objective_section.notes[0].text == "This framing looks right."

    # --- 8. ZH -> EN and bilingual reply. ---
    zh_request = LanguageDraftRequest(mode="chinese_to_english", user_input="能不能130k成交？", input_language="zh", tone="neutral")
    variants = language_service.phrase_in_english(zh_request, case, ai_client=ai_client, brief=brief)
    assert 1 <= len(variants) <= 3

    reply_request_en = LanguageDraftRequest(mode="reply_to_counterpart", user_input="We can only extend the deadline by one week.", input_language="en", tone="neutral")
    reply_en = language_service.draft_bilingual_reply(reply_request_en, case, ai_client=ai_client, brief=brief)
    assert reply_en.chinese_draft and reply_en.english_draft

    reply_request_zh = LanguageDraftRequest(mode="reply_to_counterpart", user_input="我们只能延期一周。", input_language="zh", tone="neutral")
    reply_zh = language_service.draft_bilingual_reply(reply_request_zh, case, ai_client=ai_client, brief=brief)
    assert reply_zh.chinese_draft and reply_zh.english_draft

    # --- 9. Export. ---
    markdown = brief_service.render_brief_markdown(brief)
    case_json = brief_service.export_case_json(case)
    trace_json = brief_service.export_pipeline_trace(case)
    assert "This framing looks right." in markdown  # judgment included by default
    assert case.case_id in case_json
    assert "documents" in trace_json

    # --- Never disclosed anywhere along the way. ---
    if walk_away.estimated_reservation_value and walk_away.estimated_reservation_value.current_value:
        assert walk_away.estimated_reservation_value.current_value not in markdown
