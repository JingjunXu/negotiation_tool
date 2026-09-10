from pathlib import Path

from negotiation_copilot.ai_client import (
    AgreementRequest,
    BilingualReplyRequest,
    BriefRequest,
    ConstraintRequest,
    ExtractionRequest,
    HaggleRequest,
    InterestRequest,
    PhraseInEnglishRequest,
    PositionMapRequest,
    PositionToMap,
    ReadPDFRequest,
    RelationshipCueRequest,
    WalkAwayRequest,
)
from negotiation_copilot.models import (
    Conflict,
    ConflictingValue,
    Constraint,
    Evidence,
    InterestItem,
    LanguageDraftRequest,
    NegotiationCase,
    NegotiationOption,
    ReviewedText,
)
from negotiation_copilot.fake_clients import FIXTURES_DIR, FakeAIClient
from negotiation_copilot.models import TextUnit

REPO_ROOT = Path(__file__).resolve().parent.parent

FIXTURE_PATH = FIXTURES_DIR / "sample_native_and_blank.pdf"


def test_known_fixture_returns_canned_content_with_correct_page_number():
    data = FIXTURE_PATH.read_bytes()
    client = FakeAIClient()

    [result] = client.read_pdf(ReadPDFRequest(document_id="doc-1", filename="sample.pdf", data=data, page_numbers=[2]))

    assert result.page_number == 2
    assert result.status == "success"
    assert "$85,000" in result.content
    assert result.document_id == "doc-1"


def test_unknown_content_returns_honest_placeholder_not_invented_text():
    client = FakeAIClient()
    data = b"%PDF-1.4 arbitrary uploaded content the fake client has never seen"

    [result] = client.read_pdf(ReadPDFRequest(document_id="doc-2", filename="real_material.pdf", data=data, page_numbers=[3]))

    assert result.page_number == 3
    assert result.status == "needs_review"
    assert result.content == ""
    assert "fake_mode_no_ai_reading" in result.quality_flags


def test_fixture_file_exists():
    assert FIXTURE_PATH.exists(), "checked-in fixture referenced by fake_clients manifest is missing"


def test_relationship_cue_heuristics_find_real_signals():
    text = (
        "This is a DRAFT agreement dated March 3, 2025. As discussed in the meeting "
        "with the client, see Document 10 for background. Minutes will follow next week."
    )
    client = FakeAIClient()
    request = RelationshipCueRequest(
        document_id="doc-1",
        filename="notes.txt",
        units=[TextUnit(document_id="doc-1", paragraph_id="para-1", text=text)],
    )

    cues = client.extract_relationship_cues(request)
    cue_types = {c.cue_type for c in cues}

    assert "date" in cue_types
    assert "version" in cue_types
    assert "cross_reference" in cue_types
    assert "relative_time" in cue_types
    assert "document_role" in cue_types
    for cue in cues:
        assert cue.excerpt in text or cue.excerpt.strip() in text
        assert cue.document_id == "doc-1"
        assert cue.paragraph_id == "para-1"


def test_relationship_cue_heuristics_never_invent_on_plain_text():
    client = FakeAIClient()
    request = RelationshipCueRequest(
        document_id="doc-1",
        filename="notes.txt",
        units=[TextUnit(document_id="doc-1", paragraph_id="para-1", text="Nothing notable here at all.")],
    )
    assert client.extract_relationship_cues(request) == []


def test_relationship_cue_heuristics_work_on_real_material_text():
    from negotiation_copilot import pdf_ingestion
    from negotiation_copilot.config import Config

    cfg = Config(
        openai_api_key=None, openai_model=None, openai_store_responses=False, run_live_openai_tests=False,
        app_data_dir=Path("./data"), max_upload_mb=25, max_pdf_pages=50, log_level="INFO",
    )
    path = REPO_ROOT / "0902files" / "10_WHO_Regional_Office_Report.pdf"
    pages = pdf_ingestion.extract_native_pages("doc-real", path.name, path.read_bytes(), config=cfg)

    client = FakeAIClient()
    request = RelationshipCueRequest(
        document_id="doc-real",
        filename=path.name,
        units=[TextUnit(document_id="doc-real", page_number=p.page_number, text=p.content) for p in pages],
    )
    cues = client.extract_relationship_cues(request)

    # This material bundles numbered sub-documents (e.g. "DOCUMENT 10", "22. X-Post..."),
    # which the cross_reference heuristic should pick up without any fixture.
    assert any(c.cue_type == "cross_reference" for c in cues)
    for cue in cues:
        assert cue.excerpt  # never an empty/invented excerpt


def test_extraction_never_invents_semantic_fields():
    client = FakeAIClient()
    request = ExtractionRequest(
        document_id="doc-1",
        filename="notes.txt",
        units=[TextUnit(document_id="doc-1", paragraph_id="para-1", text="A short note with no clear negotiation content.")],
    )
    extraction = client.extract_document(request)

    # Fields that would require real language understanding to fill honestly
    # stay empty/unknown rather than being guessed.
    assert extraction.my_role is None
    assert extraction.counterpart_role is None
    assert extraction.objective is None
    assert extraction.batna is None
    assert extraction.interests == []
    assert extraction.positions == []
    assert extraction.issues == []


def test_extraction_detects_deadline_from_date_plus_keyword():
    client = FakeAIClient()
    text = "The proposal deadline is March 3, 2025. Please respond before then."
    request = ExtractionRequest(
        document_id="doc-1", filename="notes.txt",
        units=[TextUnit(document_id="doc-1", paragraph_id="para-1", text=text)],
    )
    extraction = client.extract_document(request)

    assert len(extraction.deadlines) == 1
    assert extraction.deadlines[0].date_text == "March 3, 2025"
    assert extraction.deadlines[0].evidence[0].document_id == "doc-1"


def test_extraction_surfaces_literal_question_sentences():
    client = FakeAIClient()
    text = "We are unsure about the timeline. What is the actual deadline for delivery?"
    request = ExtractionRequest(
        document_id="doc-1", filename="notes.txt",
        units=[TextUnit(document_id="doc-1", paragraph_id="para-1", text=text)],
    )
    extraction = client.extract_document(request)

    assert len(extraction.open_questions) == 1
    assert extraction.open_questions[0].question == "What is the actual deadline for delivery?"


def test_extraction_summary_bullets_always_have_real_evidence():
    client = FakeAIClient()
    request = ExtractionRequest(
        document_id="doc-1", filename="notes.txt",
        units=[TextUnit(document_id="doc-1", paragraph_id="para-1", text="This is a plain sentence with no special cues at all.")],
    )
    extraction = client.extract_document(request)

    assert len(extraction.summary.bullets) >= 1
    for bullet in extraction.summary.bullets:
        assert bullet.evidence.excerpt
        assert bullet.evidence.document_id == "doc-1"


def test_fake_interests_relabel_hard_constraints_as_needs_only():
    constraint_statement = ReviewedText(
        current_value="Cannot exceed 60 day terms", ai_original_value="Cannot exceed 60 day terms",
        evidence_status="explicit", evidence=[],
    )
    request = InterestRequest(
        my_context="irrelevant text", counterpart_context="irrelevant text",
        my_hard_constraints=[Constraint(statement=constraint_statement, source_type="principal_mandate")],
    )
    items = FakeAIClient().analyze_interests(request)

    assert len(items) == 1
    assert items[0].party == "me"
    assert items[0].category == "need"
    assert items[0].is_hypothesis is False
    assert items[0].statement.current_value == "Cannot exceed 60 day terms"


def test_fake_interests_never_fabricate_fears_motives_or_values():
    request = InterestRequest(my_context="Some text", counterpart_context="Some text", my_hard_constraints=[])
    items = FakeAIClient().analyze_interests(request)
    assert items == []
    assert all(i.category != "fear" for i in items)


def test_fake_position_links_use_shared_document_id_as_weak_signal():
    shared_evidence = [Evidence(document_id="doc-1", excerpt="x")]
    position = PositionToMap(
        ref="issue:1:me", party="me",
        statement=ReviewedText(current_value="$120k", evidence=shared_evidence),
    )
    matching_interest = InterestItem(
        party="me", category="need",
        statement=ReviewedText(current_value="cash flow", evidence=shared_evidence),
    )
    other_interest = InterestItem(
        party="me", category="need",
        statement=ReviewedText(current_value="unrelated", evidence=[Evidence(document_id="doc-2", excerpt="y")]),
    )
    request = PositionMapRequest(positions=[position], interests=[matching_interest, other_interest])

    [link] = FakeAIClient().map_positions_to_interests(request)

    assert link.ref == "issue:1:me"
    assert link.underlying_interest_ids == [matching_interest.id]


def test_fake_agreement_landscape_only_reuses_existing_conflicts():
    conflict = Conflict(
        field_description="Deadline date",
        values=[ConflictingValue(document_id="doc-a", value="March 1", evidence=Evidence(document_id="doc-a", excerpt="March 1"))],
    )
    request = AgreementRequest(context="irrelevant", conflicts=[conflict])
    items = FakeAIClient().map_agreement_landscape(request)

    assert len(items) == 1
    assert items[0].standing == "contested"
    assert items[0].conflict_id == conflict.id


def test_fake_agreement_landscape_empty_without_conflicts():
    request = AgreementRequest(context="irrelevant", conflicts=[])
    assert FakeAIClient().map_agreement_landscape(request) == []


def test_fake_walk_away_reports_unknown_batna_honestly():
    draft = FakeAIClient().analyze_walk_away(WalkAwayRequest(context="anything at all"))
    assert draft.batna_quality == "unknown"
    assert draft.my_batna.value is None
    assert draft.estimated_reservation_value is None
    assert draft.exit_script  # still a usable, generic script


def test_fake_classify_constraints_only_proposes_known_redline_sources():
    redline_eligible = Constraint(
        statement=ReviewedText(current_value="No terms beyond 60 days", ai_original_value="No terms beyond 60 days", evidence_status="explicit"),
        source_type="principal_mandate",
    )
    unknown_source = Constraint(
        statement=ReviewedText(current_value="Some vague limit", ai_original_value="Some vague limit", evidence_status="unknown"),
        source_type="unknown",
    )
    request = ConstraintRequest(context="irrelevant", has_batna=False, constraints=[redline_eligible, unknown_source])
    draft = FakeAIClient().classify_constraints(request)

    assert len(draft.redline_candidates) == 1
    assert draft.redline_candidates[0].statement.value == "No terms beyond 60 days"
    assert draft.bottomline_candidates == []  # never guesses a direction/rationale


def test_fake_haggle_plan_is_always_valid_and_honest_about_missing_data():
    option = NegotiationOption(
        title="Staged payments", description="x", option_type="time", serves_my_interest_ids=[],
        serves_their_interest_ids=[], cost_to_me="low", value_to_them_hypothesis="medium", evidence_status="inferred",
    )
    request = HaggleRequest(context="irrelevant", options=[option], trade_currencies=[])
    draft = FakeAIClient().build_haggle_plan(request)

    assert draft.justification_standard.strip()  # always non-empty, never crashes the model layer
    assert draft.anchor.strip()
    assert draft.concession_ladder == []  # never invents specific numbers with no basis
    assert len(draft.counter_tactics) == 6
    assert draft.packages
    assert draft.packages[0].option_ids == [option.id]  # only ever references real options


def test_fake_generate_brief_uses_only_real_case_data():
    case = NegotiationCase(
        my_role=ReviewedText(current_value="Vendor", ai_original_value="Vendor", evidence_status="explicit"),
        counterpart_role=ReviewedText(current_value="Buyer", ai_original_value="Buyer", evidence_status="explicit"),
        objective=ReviewedText(current_value="Secure renewal", ai_original_value="Secure renewal", evidence_status="explicit"),
    )
    draft = FakeAIClient().generate_brief(BriefRequest(case=case))

    assert "Vendor" in draft.case_summary
    assert "Buyer" in draft.case_summary
    assert draft.objective_summary == "Secure renewal"


def test_fake_generate_brief_honest_when_case_is_empty():
    draft = FakeAIClient().generate_brief(BriefRequest(case=NegotiationCase()))
    assert "Unknown" in draft.case_summary
    assert draft.objective_summary == "Not established."
    assert draft.success_criteria == []
    assert draft.questions_to_ask == []


def test_fake_phrase_in_english_never_pretends_to_translate():
    request = PhraseInEnglishRequest(
        draft_request=LanguageDraftRequest(mode="chinese_to_english", user_input="能不能120k成交？", input_language="zh", tone="neutral"),
        context="",
    )
    [variant] = FakeAIClient().phrase_in_english(request)
    assert "Fake mode" in variant.english_draft
    assert "能不能120k成交" in variant.english_draft
    assert variant.chinese_back_translation == "能不能120k成交？"


def test_fake_bilingual_reply_never_pretends_to_translate():
    request = BilingualReplyRequest(
        draft_request=LanguageDraftRequest(mode="reply_to_counterpart", user_input="他们说可以谈", input_language="zh", tone="neutral"),
        context="",
    )
    draft = FakeAIClient().draft_bilingual_reply(request)
    assert "Fake mode" in draft.english_draft
    assert "Fake mode" in draft.chinese_draft


def test_extraction_works_on_real_material_text():
    from negotiation_copilot import pdf_ingestion
    from negotiation_copilot.config import Config
    from negotiation_copilot.material_organization_service import text_units_from_pdf_pages

    cfg = Config(
        openai_api_key=None, openai_model=None, openai_store_responses=False, run_live_openai_tests=False,
        app_data_dir=Path("./data"), max_upload_mb=25, max_pdf_pages=50, log_level="INFO",
    )
    path = REPO_ROOT / "0902files" / "10_WHO_Regional_Office_Report.pdf"
    pages = pdf_ingestion.extract_native_pages("doc-real", path.name, path.read_bytes(), config=cfg)
    units = text_units_from_pdf_pages(pages)

    extraction = FakeAIClient().extract_document(ExtractionRequest(document_id="doc-real", filename=path.name, units=units))
    full_text = "\n".join(u.text for u in units)

    assert extraction.document_id == "doc-real"
    assert len(extraction.summary.bullets) >= 1
    for bullet in extraction.summary.bullets:
        assert bullet.evidence.excerpt in full_text  # real text, never fabricated
