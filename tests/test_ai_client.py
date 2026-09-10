from pathlib import Path

import httpx
import openai
import pytest

from negotiation_copilot import ai_client as ai_client_module
from negotiation_copilot.ai_client import (
    AgreementRequest,
    AIAgreementBatch,
    AIAgreementItemDraft,
    AIInterestBatch,
    AIInterestItemDraft,
    AIIssueDraft,
    AIPageReading,
    AIPageReadingBatch,
    AIPositionLinkBatch,
    AIPositionLinkDraft,
    AIReviewedText,
    ConsolidationPlan,
    ConsolidationRequest,
    DocumentExtractionDraft,
    DocumentMeta,
    AIDocumentSummaryDraft,
    ExtractionRequest,
    InterestRequest,
    IssueGroupDraft,
    MaterialOrganizationDraft,
    MaterialOrganizationRequest,
    OpenAIClient,
    PositionMapRequest,
    PositionToMap,
    ReadPDFRequest,
    AIBilingualReplyDraft,
    AIBottomlineDraft,
    AIEnglishPhraseBatch,
    AIEnglishVariantDraft,
    AIOptionDraft,
    AIRedlineDraft,
    AIWalkAwayDraft,
    BilingualReplyRequest,
    BriefProseDraft,
    BriefRequest,
    ConstraintClassificationDraft,
    ConstraintRequest,
    HaggleRequest,
    HagglePlanDraft,
    OptionBatch,
    OptionRequest,
    PhraseInEnglishRequest,
    RelationshipCueBatch,
    RelationshipCueDraft,
    RelationshipCueRequest,
    WalkAwayRequest,
    render_pages_as_png,
)
from negotiation_copilot.config import Config
from negotiation_copilot.models import InterestItem, LanguageDraftRequest, NegotiationCase, ReviewedText, TextUnit


def _config(**overrides):
    defaults = dict(
        openai_api_key="sk-test",
        openai_model="gpt-test",
        openai_store_responses=False,
        run_live_openai_tests=False,
        app_data_dir=Path("./data"),
        max_upload_mb=25,
        max_pdf_pages=50,
        log_level="INFO",
    )
    defaults.update(overrides)
    return Config(**defaults)


def _bad_request_error() -> openai.BadRequestError:
    request = httpx.Request("POST", "https://api.openai.com/v1/responses")
    response = httpx.Response(status_code=400, request=request)
    return openai.BadRequestError("file input not supported", response=response, body=None)


class _FakeResponse:
    def __init__(self, batch: AIPageReadingBatch):
        self.output_parsed = batch


def test_requires_api_key():
    with pytest.raises(ValueError):
        OpenAIClient(_config(openai_api_key=None))


def test_requires_model():
    with pytest.raises(ValueError):
        OpenAIClient(_config(openai_model=None))


def test_read_pdf_via_file_normalizes_to_page_result(monkeypatch):
    client = OpenAIClient(_config())
    batch = AIPageReadingBatch(
        pages=[
            AIPageReading(page_number=2, content="Second page text", key_items=["$100k"], quality_flags=[], status="success")
        ]
    )
    monkeypatch.setattr(client._client.responses, "parse", lambda **kwargs: _FakeResponse(batch))

    results = client.read_pdf(ReadPDFRequest(document_id="doc-1", filename="brief.pdf", data=b"%PDF-1.4 fake", page_numbers=[2]))

    assert len(results) == 1
    result = results[0]
    assert result.document_id == "doc-1"
    assert result.page_number == 2
    assert result.reading_method == "ai_pdf"
    assert result.status == "success"


def test_read_pdf_falls_back_to_vision_on_bad_request(monkeypatch, tmp_path):
    import pymupdf as fitz

    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Rendered fallback page", fontsize=11)
    pdf_bytes = doc.tobytes()

    client = OpenAIClient(_config())

    calls = {"count": 0}

    def fake_parse(**kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            raise _bad_request_error()
        batch = AIPageReadingBatch(
            pages=[AIPageReading(page_number=1, content="Read via vision", key_items=[], quality_flags=[], status="success")]
        )
        return _FakeResponse(batch)

    monkeypatch.setattr(client._client.responses, "parse", fake_parse)

    results = client.read_pdf(ReadPDFRequest(document_id="doc-1", filename="brief.pdf", data=pdf_bytes, page_numbers=[1]))

    assert calls["count"] == 2
    assert len(results) == 1
    assert results[0].reading_method == "ai_vision"
    assert results[0].status == "success"


def test_read_pdf_raises_when_no_fallback_needed_and_no_parsed_output(monkeypatch):
    client = OpenAIClient(_config())
    monkeypatch.setattr(client._client.responses, "parse", lambda **kwargs: _FakeResponse(None))
    with pytest.raises(RuntimeError):
        client.read_pdf(ReadPDFRequest(document_id="doc-1", filename="brief.pdf", data=b"%PDF-1.4 fake", page_numbers=[1]))


def test_extract_relationship_cues_normalizes_to_relationship_cue(monkeypatch):
    client = OpenAIClient(_config())
    batch = RelationshipCueBatch(
        cues=[
            RelationshipCueDraft(
                cue_type="date", normalized_value="March 3, 2025", excerpt="dated March 3, 2025",
                page_number=None, paragraph_id="para-1",
            )
        ]
    )
    monkeypatch.setattr(client._client.responses, "parse", lambda **kwargs: _FakeResponse(batch))

    request = RelationshipCueRequest(
        document_id="doc-1",
        filename="brief.txt",
        units=[TextUnit(document_id="doc-1", paragraph_id="para-1", text="Agreement dated March 3, 2025.")],
    )
    cues = client.extract_relationship_cues(request)

    assert len(cues) == 1
    assert cues[0].document_id == "doc-1"
    assert cues[0].cue_type == "date"
    assert cues[0].paragraph_id == "para-1"


def test_organize_materials_forces_unconfirmed_state(monkeypatch):
    client = OpenAIClient(_config())
    draft = MaterialOrganizationDraft(
        organization_mode="chronological", temporal_order_applicable=True,
        proposed_order=["doc-1", "doc-2"], groups=[], relations=[],
        confidence="high", rationale="Dated cues place doc-1 before doc-2.",
        unresolved_ambiguities=[],
    )
    monkeypatch.setattr(client._client.responses, "parse", lambda **kwargs: _FakeResponse(draft))

    request = MaterialOrganizationRequest(
        documents=[
            DocumentMeta(document_id="doc-1", filename="a.txt", upload_index=0),
            DocumentMeta(document_id="doc-2", filename="b.txt", upload_index=1),
        ],
        cues=[],
    )
    result = client.organize_materials(request)

    assert result.organization_mode == "chronological"
    assert result.proposed_order == ["doc-1", "doc-2"]
    assert result.confirmed_order is None
    assert result.review_status == "unreviewed"


def test_extract_document_normalizes_draft_and_generates_ids(monkeypatch):
    client = OpenAIClient(_config())
    draft = DocumentExtractionDraft(
        summary=AIDocumentSummaryDraft(bullets=[], role_and_purpose="Role brief", relationship_to_others=None, warnings=[]),
        my_role=AIReviewedText(value="Vendor", evidence_status="explicit", evidence=[]),
        counterpart_role=None,
        context=None,
        objective=None,
        interests=[],
        positions=[],
        batna=None,
        issues=[
            AIIssueDraft(
                title="Payment terms",
                my_position=AIReviewedText(value="$120k in 30 days", evidence_status="explicit", evidence=[]),
                counterpart_position=None, target=None, acceptable_range=None,
                priority="high", flexibility="flexible", evidence=[],
            )
        ],
        targets=[], hard_constraints=[], authority_limits=[], deadlines=[],
        possible_concessions=[], counterpart_information=[], open_questions=[], warnings=[],
    )
    monkeypatch.setattr(client._client.responses, "parse", lambda **kwargs: _FakeResponse(draft))

    request = ExtractionRequest(
        document_id="doc-1", filename="brief.txt",
        units=[TextUnit(document_id="doc-1", paragraph_id="para-1", text="We want $120k in 30 days.")],
    )
    extraction = client.extract_document(request)

    assert extraction.document_id == "doc-1"
    assert extraction.my_role.current_value == "Vendor"
    assert extraction.my_role.ai_original_value == "Vendor"
    assert len(extraction.issues) == 1
    assert extraction.issues[0].id  # generated, never asked of the AI
    assert extraction.issues[0].my_position.current_value == "$120k in 30 days"


def test_consolidate_case_returns_plan_not_full_case(monkeypatch):
    client = OpenAIClient(_config())
    plan = ConsolidationPlan(issue_groups=[IssueGroupDraft(issue_refs=["doc-1:a", "doc-2:b"], merged_title="Price")])
    monkeypatch.setattr(client._client.responses, "parse", lambda **kwargs: _FakeResponse(plan))

    request = ConsolidationRequest(
        documents=[DocumentMeta(document_id="doc-1", filename="a.txt", upload_index=0)],
        extractions=[],
    )
    result = client.consolidate_case(request)

    assert isinstance(result, ConsolidationPlan)
    assert result.issue_groups[0].merged_title == "Price"


def test_analyze_interests_makes_separate_calls_per_party(monkeypatch):
    client = OpenAIClient(_config())
    calls = []

    def fake_parse(**kwargs):
        calls.append(kwargs["input"][0]["content"])
        party = "me" if "Party: me" in kwargs["input"][0]["content"] else "counterpart"
        item = AIInterestItemDraft(
            category="need", statement=AIReviewedText(value=f"{party} needs X", evidence_status="explicit", evidence=[]),
            verification_question=None,
        )
        return _FakeResponse(AIInterestBatch(items=[item]))

    monkeypatch.setattr(client._client.responses, "parse", fake_parse)

    request = InterestRequest(my_context="My confidential stuff", counterpart_context="Shared stuff only")
    items = client.analyze_interests(request)

    assert len(calls) == 2
    assert len(items) == 2
    me_item = next(i for i in items if i.party == "me")
    counterpart_item = next(i for i in items if i.party == "counterpart")
    assert me_item.is_hypothesis is False
    assert counterpart_item.is_hypothesis is True
    assert "My confidential stuff" not in "".join(c for c in calls if "Party: counterpart" in c)


def test_map_positions_to_interests_returns_drafts(monkeypatch):
    client = OpenAIClient(_config())
    batch = AIPositionLinkBatch(
        links=[
            AIPositionLinkDraft(
                ref="issue:1:me", underlying_interest_ids=["interest-1"],
                inference_basis="explicit", reframe_question="Why?", misalignment_note=None,
            )
        ]
    )
    monkeypatch.setattr(client._client.responses, "parse", lambda **kwargs: _FakeResponse(batch))

    request = PositionMapRequest(
        positions=[PositionToMap(ref="issue:1:me", party="me", statement=ReviewedText(current_value="$120k"))],
        interests=[InterestItem(id="interest-1", party="me", category="need", statement=ReviewedText(current_value="cash flow"))],
    )
    drafts = client.map_positions_to_interests(request)

    assert len(drafts) == 1
    assert drafts[0].underlying_interest_ids == ["interest-1"]


def test_map_positions_to_interests_skips_call_when_no_positions():
    client = OpenAIClient(_config())
    result = client.map_positions_to_interests(PositionMapRequest(positions=[], interests=[]))
    assert result == []


def test_map_agreement_landscape_returns_drafts(monkeypatch):
    client = OpenAIClient(_config())
    batch = AIAgreementBatch(
        items=[
            AIAgreementItemDraft(
                kind="fact", statement="Started in March", standing="shared",
                my_view="March", counterpart_view="March", conflict_id=None,
                verification_question=None, evidence=[],
            )
        ]
    )
    monkeypatch.setattr(client._client.responses, "parse", lambda **kwargs: _FakeResponse(batch))

    result = client.map_agreement_landscape(AgreementRequest(context="some context", conflicts=[]))
    assert len(result) == 1
    assert result[0].standing == "shared"


def test_analyze_walk_away_returns_draft(monkeypatch):
    client = OpenAIClient(_config())
    draft = AIWalkAwayDraft(
        my_batna=AIReviewedText(value="Secondary buyer", evidence_status="inferred", evidence=[]),
        batna_quality="moderate", quality_rationale="x", actions_to_improve_batna=[],
        estimated_reservation_value=None, reservation_derivation=None,
        counterpart_batna_hypothesis=None, tests_to_probe_their_batna=[],
        walk_away_triggers=[], exit_script="We need more time.", do_not_disclose=[],
    )
    monkeypatch.setattr(client._client.responses, "parse", lambda **kwargs: _FakeResponse(draft))

    result = client.analyze_walk_away(WalkAwayRequest(context="some context"))
    assert result.batna_quality == "moderate"
    assert result.exit_script == "We need more time."


def test_classify_constraints_returns_draft(monkeypatch):
    client = OpenAIClient(_config())
    draft = ConstraintClassificationDraft(
        redline_candidates=[
            AIRedlineDraft(
                statement=AIReviewedText(value="No terms beyond 60 days", evidence_status="explicit", evidence=[]),
                source_type="principal_mandate", consequence_if_crossed="Void", evidence=[],
            )
        ],
        bottomline_candidates=[
            AIBottomlineDraft(
                issue_id=None, threshold_value=AIReviewedText(value="$100k", evidence_status="inferred", evidence=[]),
                direction="min", rationale="x", linked_batna_reference=None, risk_if_crossed="y",
                revisit_conditions=[], evidence=[],
            )
        ],
    )
    monkeypatch.setattr(client._client.responses, "parse", lambda **kwargs: _FakeResponse(draft))

    result = client.classify_constraints(ConstraintRequest(context="some context", has_batna=False))
    assert len(result.redline_candidates) == 1
    assert len(result.bottomline_candidates) == 1


def test_generate_options_returns_drafts(monkeypatch):
    client = OpenAIClient(_config())
    batch = OptionBatch(
        options=[
            AIOptionDraft(
                title="Staged payments", description="x", option_type="time",
                serves_my_interest_ids=["interest-1"], serves_their_interest_ids=[],
                cost_to_me="low", value_to_them_hypothesis="medium", depends_on=[], evidence_status="inferred",
            )
        ]
    )
    monkeypatch.setattr(client._client.responses, "parse", lambda **kwargs: _FakeResponse(batch))

    result = client.generate_options(OptionRequest(context="ctx", interests=[]))
    assert len(result) == 1
    assert result[0].option_type == "time"


def test_build_haggle_plan_returns_draft(monkeypatch):
    client = OpenAIClient(_config())
    draft = HagglePlanDraft(packages=[], anchor="$130k", justification_standard="Market rate", concession_ladder=[], counter_tactics=[])
    monkeypatch.setattr(client._client.responses, "parse", lambda **kwargs: _FakeResponse(draft))

    result = client.build_haggle_plan(HaggleRequest(context="ctx", options=[], trade_currencies=[]))
    assert result.anchor == "$130k"
    assert result.justification_standard == "Market rate"


def test_generate_brief_returns_prose_draft(monkeypatch):
    client = OpenAIClient(_config())
    draft = BriefProseDraft(
        case_summary="A vendor renewal negotiation.", objective_summary="Secure renewal.",
        success_criteria=["Achieve target price"], opening_plan="We're glad to continue this conversation.",
        questions_to_ask=["What is your timeline?"],
    )
    monkeypatch.setattr(client._client.responses, "parse", lambda **kwargs: _FakeResponse(draft))

    result = client.generate_brief(BriefRequest(case=NegotiationCase()))
    assert result.case_summary == "A vendor renewal negotiation."
    assert result.questions_to_ask == ["What is your timeline?"]


def _draft_request(**overrides):
    defaults = dict(mode="chinese_to_english", user_input="能不能120k成交？", input_language="zh", tone="neutral")
    defaults.update(overrides)
    return LanguageDraftRequest(**defaults)


def test_phrase_in_english_returns_variants(monkeypatch):
    client = OpenAIClient(_config())
    batch = AIEnglishPhraseBatch(
        variants=[AIEnglishVariantDraft(label="natural", english_draft="Could we settle at $120k?", chinese_back_translation="能不能120k成交？", risk_flags=[])]
    )
    monkeypatch.setattr(client._client.responses, "parse", lambda **kwargs: _FakeResponse(batch))

    result = client.phrase_in_english(PhraseInEnglishRequest(draft_request=_draft_request(), context=""))
    assert len(result) == 1
    assert result[0].label == "natural"


def test_draft_bilingual_reply_returns_draft(monkeypatch):
    client = OpenAIClient(_config())
    draft = AIBilingualReplyDraft(
        counterpart_summary_zh="他们同意了", counterpart_summary_en="They agreed",
        points_to_verify=[], chinese_draft="好的", english_draft="Understood", risk_flags=[],
    )
    monkeypatch.setattr(client._client.responses, "parse", lambda **kwargs: _FakeResponse(draft))

    result = client.draft_bilingual_reply(BilingualReplyRequest(draft_request=_draft_request(mode="reply_to_counterpart"), context=""))
    assert result.english_draft == "Understood"


def test_render_pages_as_png_produces_valid_png_bytes():
    import pymupdf as fitz

    doc = fitz.open()
    doc.new_page()
    doc.new_page()
    pdf_bytes = doc.tobytes()

    rendered = render_pages_as_png(pdf_bytes, [1, 2])
    assert set(rendered.keys()) == {1, 2}
    for png_bytes in rendered.values():
        assert png_bytes.startswith(b"\x89PNG\r\n\x1a\n")
