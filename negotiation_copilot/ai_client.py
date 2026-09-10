"""AIClient boundary (SPEC §13.1). Grows one method per milestone task.

Streamlit pages never assemble prompts or call OpenAI directly; they go
through a service module, which goes through this boundary.
"""

import base64
from pathlib import Path
from typing import Literal, Protocol

import pymupdf  # PyMuPDF — page rendering, adapter-internal only (SPEC §13.3)
import openai
from openai import OpenAI
from pydantic import BaseModel

from .config import Config
from .models import (
    AgreementItem,
    Conflict,
    Constraint,
    ConcessionStep,
    CounterTactic,
    Deadline,
    DocumentExtraction,
    DocumentGroup,
    DocumentRelation,
    DocumentSummary,
    Evidence,
    InterestItem,
    LanguageDraftRequest,
    MaterialOrganizationResult,
    NegotiationCase,
    NegotiationIssue,
    NegotiationOption,
    OpenQuestion,
    PDFPageResult,
    PositionInterestLink,
    RelationshipCue,
    ReviewedText,
    SummaryBullet,
    TextUnit,
    TradeCurrency,
)

_RENDER_ZOOM = 2.0  # ~144 DPI; legible for a vision model without huge payloads

PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"


def _load_prompt(name: str) -> str:
    return (PROMPTS_DIR / name).read_text(encoding="utf-8")


class ReadPDFRequest(BaseModel):
    document_id: str
    filename: str
    data: bytes
    page_numbers: list[int]  # 1-based pages to (re-)read via AI


class AIPageReading(BaseModel):
    page_number: int
    content: str
    key_items: list[str]
    quality_flags: list[str]
    status: Literal["success", "needs_review", "failed"]
    error_type: str | None = None


class AIPageReadingBatch(BaseModel):
    pages: list[AIPageReading]


class RelationshipCueRequest(BaseModel):
    document_id: str
    filename: str
    units: list[TextUnit]


class RelationshipCueDraft(BaseModel):
    cue_type: Literal["date", "relative_time", "version", "cross_reference", "topic", "document_role"]
    normalized_value: str | None
    excerpt: str
    page_number: int | None = None
    paragraph_id: str | None = None


class RelationshipCueBatch(BaseModel):
    cues: list[RelationshipCueDraft]


class DocumentMeta(BaseModel):
    document_id: str
    filename: str
    upload_index: int


class MaterialOrganizationRequest(BaseModel):
    documents: list[DocumentMeta]
    cues: list[RelationshipCue]


class ExtractionRequest(BaseModel):
    document_id: str
    filename: str
    units: list[TextUnit]


class AIReviewedText(BaseModel):
    """AI-facing shape for a ReviewedText: the AI supplies one `value`, which
    the service copies into both `current_value` and `ai_original_value` —
    the AI must never be asked to keep two copies in sync itself."""

    value: str | None
    evidence_status: Literal["explicit", "inferred", "unknown"]
    evidence: list[Evidence]


class AISummaryBulletDraft(BaseModel):
    text: str
    evidence: Evidence


class AIDocumentSummaryDraft(BaseModel):
    bullets: list[AISummaryBulletDraft]
    role_and_purpose: str | None
    relationship_to_others: str | None
    warnings: list[str]


class AIIssueDraft(BaseModel):
    title: str
    my_position: AIReviewedText | None
    counterpart_position: AIReviewedText | None
    target: AIReviewedText | None
    acceptable_range: AIReviewedText | None
    priority: Literal["high", "medium", "low", "unknown"]
    flexibility: Literal["flexible", "firm", "unknown"]
    evidence: list[Evidence]


class AIConstraintDraft(BaseModel):
    statement: AIReviewedText
    source_type: Literal["instructor_rules", "authority_limit", "legal_ethical", "principal_mandate", "unknown"]
    evidence: list[Evidence]


class AIDeadlineDraft(BaseModel):
    description: str
    date_text: str | None
    evidence: list[Evidence]


class AIOpenQuestionDraft(BaseModel):
    question: str
    context: str | None
    evidence: list[Evidence]


class DocumentExtractionDraft(BaseModel):
    summary: AIDocumentSummaryDraft
    my_role: AIReviewedText | None
    counterpart_role: AIReviewedText | None
    context: AIReviewedText | None
    objective: AIReviewedText | None
    interests: list[AIReviewedText]
    positions: list[AIReviewedText]
    batna: AIReviewedText | None
    issues: list[AIIssueDraft]
    targets: list[AIReviewedText]
    hard_constraints: list[AIConstraintDraft]
    authority_limits: list[AIReviewedText]
    deadlines: list[AIDeadlineDraft]
    possible_concessions: list[AIReviewedText]
    counterpart_information: list[AIReviewedText]
    open_questions: list[AIOpenQuestionDraft]
    warnings: list[str]


def _reviewed_from_draft(draft: AIReviewedText | None, document_id: str) -> ReviewedText | None:
    if draft is None:
        return None
    evidence = [e.model_copy(update={"document_id": document_id}) for e in draft.evidence]
    return ReviewedText(
        current_value=draft.value,
        ai_original_value=draft.value,
        evidence_status=draft.evidence_status,
        evidence=evidence,
    )


def _reviewed_list_from_draft(drafts: list[AIReviewedText], document_id: str) -> list[ReviewedText]:
    return [_reviewed_from_draft(d, document_id) for d in drafts]


def reviewed_from_draft_keep_document_ids(draft: AIReviewedText | None) -> ReviewedText | None:
    """Like _reviewed_from_draft, but for calls spanning multiple documents
    at once (e.g. interests), where the AI must supply each evidence
    entry's real document_id itself — there is no single document_id to
    inject afterward."""
    if draft is None:
        return None
    return ReviewedText(
        current_value=draft.value,
        ai_original_value=draft.value,
        evidence_status=draft.evidence_status,
        evidence=draft.evidence,
    )


def document_extraction_from_draft(document_id: str, draft: DocumentExtractionDraft) -> DocumentExtraction:
    """Build the final DocumentExtraction, injecting `document_id` into every
    evidence entry and generating ids for nested items (never asked of the AI).
    Shared by OpenAIClient and FakeAIClient so both normalize identically."""
    summary = DocumentSummary(
        bullets=[
            SummaryBullet(text=b.text, evidence=b.evidence.model_copy(update={"document_id": document_id}))
            for b in draft.summary.bullets
        ],
        role_and_purpose=draft.summary.role_and_purpose,
        relationship_to_others=draft.summary.relationship_to_others,
        warnings=draft.summary.warnings,
    )

    issues = [
        NegotiationIssue(
            title=i.title,
            my_position=_reviewed_from_draft(i.my_position, document_id),
            counterpart_position=_reviewed_from_draft(i.counterpart_position, document_id),
            target=_reviewed_from_draft(i.target, document_id),
            acceptable_range=_reviewed_from_draft(i.acceptable_range, document_id),
            priority=i.priority,
            flexibility=i.flexibility,
            evidence=[e.model_copy(update={"document_id": document_id}) for e in i.evidence],
        )
        for i in draft.issues
    ]

    hard_constraints = [
        Constraint(
            statement=_reviewed_from_draft(c.statement, document_id),
            source_type=c.source_type,
            evidence=[e.model_copy(update={"document_id": document_id}) for e in c.evidence],
        )
        for c in draft.hard_constraints
    ]

    deadlines = [
        Deadline(
            description=d.description,
            date_text=d.date_text,
            evidence=[e.model_copy(update={"document_id": document_id}) for e in d.evidence],
        )
        for d in draft.deadlines
    ]

    open_questions = [
        OpenQuestion(
            question=q.question,
            context=q.context,
            related_document_ids=[document_id],
            evidence=[e.model_copy(update={"document_id": document_id}) for e in q.evidence],
        )
        for q in draft.open_questions
    ]

    return DocumentExtraction(
        document_id=document_id,
        summary=summary,
        my_role=_reviewed_from_draft(draft.my_role, document_id),
        counterpart_role=_reviewed_from_draft(draft.counterpart_role, document_id),
        context=_reviewed_from_draft(draft.context, document_id),
        objective=_reviewed_from_draft(draft.objective, document_id),
        interests=_reviewed_list_from_draft(draft.interests, document_id),
        positions=_reviewed_list_from_draft(draft.positions, document_id),
        batna=_reviewed_from_draft(draft.batna, document_id),
        issues=issues,
        targets=_reviewed_list_from_draft(draft.targets, document_id),
        hard_constraints=hard_constraints,
        authority_limits=_reviewed_list_from_draft(draft.authority_limits, document_id),
        deadlines=deadlines,
        possible_concessions=_reviewed_list_from_draft(draft.possible_concessions, document_id),
        counterpart_information=_reviewed_list_from_draft(draft.counterpart_information, document_id),
        open_questions=open_questions,
        warnings=draft.warnings,
    )


class MaterialOrganizationDraft(BaseModel):
    """AI-facing shape: excludes `confirmed_order` and `review_status`,
    which are user-workflow fields the AI must never set (SPEC §6.3: the
    user accepts, edits, or disables the proposal)."""

    organization_mode: Literal["chronological", "versioned", "thematic", "complementary", "independent", "mixed"]
    temporal_order_applicable: bool
    proposed_order: list[str] | None
    groups: list[DocumentGroup]
    relations: list[DocumentRelation]
    confidence: Literal["high", "medium", "low"]
    rationale: str
    unresolved_ambiguities: list[str]


def relationship_cues_from_batch(document_id: str, batch: RelationshipCueBatch) -> list[RelationshipCue]:
    """Shared by OpenAIClient and ClaudeCliClient so both normalize identically."""
    return [
        RelationshipCue(
            document_id=document_id,
            cue_type=cue.cue_type,
            normalized_value=cue.normalized_value,
            excerpt=cue.excerpt,
            page_number=cue.page_number,
            paragraph_id=cue.paragraph_id,
        )
        for cue in batch.cues
    ]


def organization_result_from_draft(draft: MaterialOrganizationDraft) -> MaterialOrganizationResult:
    """Shared by OpenAIClient and ClaudeCliClient; never trusts the draft's
    `confirmed_order`/`review_status` — there are none, by construction, since
    MaterialOrganizationDraft excludes those user-workflow fields."""
    return MaterialOrganizationResult(
        organization_mode=draft.organization_mode,
        temporal_order_applicable=draft.temporal_order_applicable,
        proposed_order=draft.proposed_order,
        confirmed_order=None,
        groups=draft.groups,
        relations=draft.relations,
        confidence=draft.confidence,
        rationale=draft.rationale,
        unresolved_ambiguities=draft.unresolved_ambiguities,
        review_status="unreviewed",
    )


def render_pages_as_png(data: bytes, page_numbers: list[int], *, zoom: float = _RENDER_ZOOM) -> dict[int, bytes]:
    """Render the given 1-based PDF pages to PNG bytes (adapter-internal fallback)."""
    document = pymupdf.open(stream=data, filetype="pdf")
    matrix = pymupdf.Matrix(zoom, zoom)
    rendered: dict[int, bytes] = {}
    for page_number in page_numbers:
        page = document.load_page(page_number - 1)
        pixmap = page.get_pixmap(matrix=matrix)
        rendered[page_number] = pixmap.tobytes("png")
    return rendered


class ConsolidationRequest(BaseModel):
    documents: list[DocumentMeta]
    extractions: list[DocumentExtraction]


class IssueGroupDraft(BaseModel):
    issue_refs: list[str]  # "<document_id>:<issue_id>"
    merged_title: str


class ConsolidationPlan(BaseModel):
    """Deliberately NOT a NegotiationCase (SPEC §13.1's protocol sketch says
    `consolidate_case(...) -> NegotiationCase`): the AI only decides which
    issues across documents are duplicates. The actual merge — unioning
    evidence, detecting divergent values, building Conflict records — is
    deterministic code in consolidation_service.py, so evidence can never be
    silently rewritten or dropped by a model call. See docs/DECISIONS.md T3.5.
    """

    issue_groups: list[IssueGroupDraft]


class InterestRequest(BaseModel):
    """`counterpart_context` must already have my_confidential content
    filtered out by the caller (SPEC §8.1: counterpart items may only be
    derived from shared/instructor_rules materials) — this is enforced by
    interest_service.py building the two contexts, not by prompt wording.

    `my_hard_constraints` is passed through structurally (not just folded
    into `my_context` text) so FakeAIClient can safely relabel already-
    evidenced constraints as "needs" without having to re-parse free text.
    """

    my_context: str
    counterpart_context: str
    my_hard_constraints: list[Constraint] = []


class AIInterestItemDraft(BaseModel):
    category: Literal["need", "fear", "motive", "value"]
    statement: AIReviewedText
    verification_question: str | None


class AIInterestBatch(BaseModel):
    items: list[AIInterestItemDraft]


class PositionToMap(BaseModel):
    ref: str
    party: Literal["me", "counterpart"]
    statement: ReviewedText


class PositionMapRequest(BaseModel):
    positions: list[PositionToMap]
    interests: list[InterestItem]


class AIPositionLinkDraft(BaseModel):
    ref: str
    underlying_interest_ids: list[str]
    inference_basis: str
    reframe_question: str | None
    misalignment_note: str | None


class AIPositionLinkBatch(BaseModel):
    links: list[AIPositionLinkDraft]


class AgreementRequest(BaseModel):
    context: str  # rendered case content, each evidence entry labeled with its document's scope
    conflicts: list[Conflict]


class AIAgreementItemDraft(BaseModel):
    kind: Literal["fact", "value", "process"]
    statement: str
    standing: Literal["shared", "contested", "unverified"]
    my_view: str | None
    counterpart_view: str | None
    conflict_id: str | None
    verification_question: str | None
    evidence: list[Evidence]


class AIAgreementBatch(BaseModel):
    items: list[AIAgreementItemDraft]


class ConstraintRequest(BaseModel):
    context: str
    has_batna: bool
    constraints: list[Constraint] = []  # structural pass-through for FakeAIClient; see docs/DECISIONS.md T5.2


class AIRedlineDraft(BaseModel):
    statement: AIReviewedText
    source_type: Literal["instructor_rules", "authority_limit", "legal_ethical", "principal_mandate"]
    consequence_if_crossed: str
    evidence: list[Evidence]


class AIBottomlineDraft(BaseModel):
    issue_id: str | None
    threshold_value: AIReviewedText
    direction: Literal["min", "max"]
    rationale: str
    linked_batna_reference: str | None
    risk_if_crossed: str
    revisit_conditions: list[str]
    evidence: list[Evidence]


class ConstraintClassificationDraft(BaseModel):
    redline_candidates: list[AIRedlineDraft]
    bottomline_candidates: list[AIBottomlineDraft]


class OptionRequest(BaseModel):
    context: str
    interests: list[InterestItem]
    existing_option_titles: list[str] = []


class AIOptionDraft(BaseModel):
    title: str
    description: str
    option_type: Literal["valuation", "time", "risk", "capability", "unbundle", "add_issue", "non_monetary", "process"]
    serves_my_interest_ids: list[str]
    serves_their_interest_ids: list[str]
    cost_to_me: Literal["low", "medium", "high", "unknown"]
    value_to_them_hypothesis: Literal["low", "medium", "high", "unknown"]
    depends_on: list[str]
    evidence_status: Literal["explicit", "inferred", "unknown"]


class OptionBatch(BaseModel):
    options: list[AIOptionDraft]


class HaggleRequest(BaseModel):
    context: str
    options: list[NegotiationOption]
    trade_currencies: list[TradeCurrency]


class AIPackageDraft(BaseModel):
    label: str
    option_ids: list[str]
    what_i_give: list[str]
    what_i_get: list[str]
    equivalence_note: str


class AIConcessionStepDraft(BaseModel):
    issue_id: str | None
    from_value: str
    to_value: str
    ask_in_return: str
    trigger_condition: str


class HagglePlanDraft(BaseModel):
    packages: list[AIPackageDraft]
    anchor: str
    justification_standard: str
    concession_ladder: list[AIConcessionStepDraft]
    counter_tactics: list[CounterTactic]


class BriefRequest(BaseModel):
    """Carries the case directly (not pre-rendered text) so both clients can
    work from the same structured data — OpenAIClient renders the confirmed
    subset into text itself; FakeAIClient reads fields directly rather than
    re-parsing a string."""

    case: NegotiationCase


class BriefProseDraft(BaseModel):
    case_summary: str
    objective_summary: str
    success_criteria: list[str]
    opening_plan: str
    questions_to_ask: list[str]


class PhraseInEnglishRequest(BaseModel):
    draft_request: LanguageDraftRequest
    context: str  # confirmed brief content for the user-selected sections, rendered


class AIEnglishVariantDraft(BaseModel):
    label: Literal["natural", "collaborative", "firm"]
    english_draft: str
    chinese_back_translation: str
    risk_flags: list[str]


class AIEnglishPhraseBatch(BaseModel):
    variants: list[AIEnglishVariantDraft]


class BilingualReplyRequest(BaseModel):
    draft_request: LanguageDraftRequest
    context: str


class AIBilingualReplyDraft(BaseModel):
    counterpart_summary_zh: str | None
    counterpart_summary_en: str | None
    points_to_verify: list[str]
    chinese_draft: str
    english_draft: str
    risk_flags: list[str]


class WalkAwayRequest(BaseModel):
    context: str


class AIWalkAwayDraft(BaseModel):
    my_batna: AIReviewedText
    batna_quality: Literal["strong", "moderate", "weak", "unknown"]
    quality_rationale: str
    actions_to_improve_batna: list[str]
    estimated_reservation_value: AIReviewedText | None
    reservation_derivation: str | None
    counterpart_batna_hypothesis: AIReviewedText | None
    tests_to_probe_their_batna: list[str]
    walk_away_triggers: list[str]
    exit_script: str
    do_not_disclose: list[str]


class AIClient(Protocol):
    def read_pdf(self, request: ReadPDFRequest) -> list[PDFPageResult]: ...
    def extract_relationship_cues(self, request: RelationshipCueRequest) -> list[RelationshipCue]: ...
    def organize_materials(self, request: MaterialOrganizationRequest) -> MaterialOrganizationResult: ...
    def extract_document(self, request: ExtractionRequest) -> DocumentExtraction: ...
    def consolidate_case(self, request: ConsolidationRequest) -> ConsolidationPlan: ...
    def analyze_interests(self, request: InterestRequest) -> list[InterestItem]: ...
    def map_positions_to_interests(self, request: PositionMapRequest) -> list[AIPositionLinkDraft]: ...
    def map_agreement_landscape(self, request: AgreementRequest) -> list[AIAgreementItemDraft]: ...
    def analyze_walk_away(self, request: WalkAwayRequest) -> AIWalkAwayDraft: ...
    def classify_constraints(self, request: ConstraintRequest) -> ConstraintClassificationDraft: ...
    def generate_options(self, request: OptionRequest) -> list[AIOptionDraft]: ...
    def build_haggle_plan(self, request: HaggleRequest) -> HagglePlanDraft: ...
    def generate_brief(self, request: BriefRequest) -> BriefProseDraft: ...
    def phrase_in_english(self, request: PhraseInEnglishRequest) -> list[AIEnglishVariantDraft]: ...
    def draft_bilingual_reply(self, request: BilingualReplyRequest) -> AIBilingualReplyDraft: ...


def _to_page_results(document_id: str, reading_method: str, pages: list[AIPageReading]) -> list[PDFPageResult]:
    return [
        PDFPageResult(
            document_id=document_id,
            page_number=page.page_number,
            reading_method=reading_method,
            content=page.content,
            key_items=page.key_items,
            quality_flags=page.quality_flags,
            status=page.status,
            error_type=page.error_type,
        )
        for page in pages
    ]


class OpenAIClient:
    """Real AIClient implementation, backed by the OpenAI Responses API.

    Prefers direct PDF/file input; falls back to rendering the requested
    pages as images only if the API rejects the file-input request (SPEC
    §5.2: "render pages inside the adapter only if the SDK/model requires it").
    """

    def __init__(self, config: Config):
        if config.is_fake_mode:
            raise ValueError("OpenAIClient requires OPENAI_API_KEY; use FakeAIClient in fake mode")
        if not config.openai_model:
            raise ValueError("OPENAI_MODEL must be set to use OpenAIClient")
        self._config = config
        self._client = OpenAI(api_key=config.openai_api_key)

    @property
    def cache_tag(self) -> str:
        """Identifies this client's result *provenance* for pdf_service's
        content cache, so switching models (or from FakeAIClient to this one)
        never serves a stale result produced under different assumptions."""
        return f"openai:{self._config.openai_model}"

    def read_pdf(self, request: ReadPDFRequest) -> list[PDFPageResult]:
        try:
            return self._read_pdf_via_file(request)
        except openai.BadRequestError:
            return self._read_pdf_via_vision(request)

    def _pages_prompt_text(self, request: ReadPDFRequest) -> str:
        pages_note = ", ".join(str(page) for page in request.page_numbers)
        return f"Read only these 1-based page numbers and return one entry per page: {pages_note}"

    def _parse_pages(self, content: list[dict]) -> AIPageReadingBatch:
        response = self._client.responses.parse(
            model=self._config.openai_model,
            instructions=_load_prompt("read_pdf.md"),
            input=[{"role": "user", "content": content}],
            text_format=AIPageReadingBatch,
            **self._config.response_kwargs(),
        )
        batch = response.output_parsed
        if batch is None:
            raise RuntimeError("OpenAI returned no parsed PDF reading")
        return batch

    def _read_pdf_via_file(self, request: ReadPDFRequest) -> list[PDFPageResult]:
        file_data = "data:application/pdf;base64," + base64.b64encode(request.data).decode("ascii")
        content = [
            {"type": "input_text", "text": self._pages_prompt_text(request)},
            {"type": "input_file", "filename": request.filename, "file_data": file_data},
        ]
        batch = self._parse_pages(content)
        return _to_page_results(request.document_id, "ai_pdf", batch.pages)

    def _read_pdf_via_vision(self, request: ReadPDFRequest) -> list[PDFPageResult]:
        rendered = render_pages_as_png(request.data, request.page_numbers)
        content = [{"type": "input_text", "text": self._pages_prompt_text(request)}]
        for page_number in request.page_numbers:
            image_data = "data:image/png;base64," + base64.b64encode(rendered[page_number]).decode("ascii")
            content.append({"type": "input_image", "image_url": image_data, "detail": "auto"})
        batch = self._parse_pages(content)
        return _to_page_results(request.document_id, "ai_vision", batch.pages)

    def extract_relationship_cues(self, request: RelationshipCueRequest) -> list[RelationshipCue]:
        units_text = "\n\n".join(_format_unit(unit) for unit in request.units)
        response = self._client.responses.parse(
            model=self._config.openai_model,
            instructions=_load_prompt("extract_relationship_cues.md"),
            input=[
                {
                    "role": "user",
                    "content": f"Document: {request.filename}\n\n{units_text}",
                }
            ],
            text_format=RelationshipCueBatch,
            **self._config.response_kwargs(),
        )
        batch = response.output_parsed
        if batch is None:
            raise RuntimeError(f"OpenAI returned no parsed relationship cues for {request.filename}")
        return relationship_cues_from_batch(request.document_id, batch)


    def organize_materials(self, request: MaterialOrganizationRequest) -> MaterialOrganizationResult:
        response = self._client.responses.parse(
            model=self._config.openai_model,
            instructions=_load_prompt("organize_materials.md"),
            input=[{"role": "user", "content": _format_organization_request(request)}],
            text_format=MaterialOrganizationDraft,
            **self._config.response_kwargs(),
        )
        draft = response.output_parsed
        if draft is None:
            raise RuntimeError("OpenAI returned no parsed material organization result")
        return organization_result_from_draft(draft)


    def extract_document(self, request: ExtractionRequest) -> DocumentExtraction:
        units_text = "\n\n".join(_format_unit(unit) for unit in request.units)
        response = self._client.responses.parse(
            model=self._config.openai_model,
            instructions=_load_prompt("summarize_and_extract.md"),
            input=[{"role": "user", "content": f"Document: {request.filename}\n\n{units_text}"}],
            text_format=DocumentExtractionDraft,
            **self._config.response_kwargs(),
        )
        draft = response.output_parsed
        if draft is None:
            raise RuntimeError(f"OpenAI returned no parsed extraction for {request.filename}")
        return document_extraction_from_draft(request.document_id, draft)

    def consolidate_case(self, request: ConsolidationRequest) -> ConsolidationPlan:
        response = self._client.responses.parse(
            model=self._config.openai_model,
            instructions=_load_prompt("consolidate.md"),
            input=[{"role": "user", "content": _format_consolidation_request(request)}],
            text_format=ConsolidationPlan,
            **self._config.response_kwargs(),
        )
        plan = response.output_parsed
        if plan is None:
            raise RuntimeError("OpenAI returned no parsed consolidation plan")
        return plan

    def analyze_interests(self, request: InterestRequest) -> list[InterestItem]:
        me_items = self._analyze_interests_for_party("me", request.my_context)
        counterpart_items = self._analyze_interests_for_party("counterpart", request.counterpart_context)
        return me_items + counterpart_items

    def _analyze_interests_for_party(self, party: str, context: str) -> list[InterestItem]:
        if not context.strip():
            return []
        response = self._client.responses.parse(
            model=self._config.openai_model,
            instructions=_load_prompt("analyze_interests.md"),
            input=[{"role": "user", "content": f"Party: {party}\n\n{context}"}],
            text_format=AIInterestBatch,
            **self._config.response_kwargs(),
        )
        batch = response.output_parsed
        if batch is None:
            raise RuntimeError(f"OpenAI returned no parsed interests for party={party}")
        return [
            InterestItem(
                party=party,
                category=item.category,
                statement=reviewed_from_draft_keep_document_ids(item.statement),
                verification_question=item.verification_question,
                is_hypothesis=(party == "counterpart"),
            )
            for item in batch.items
        ]

    def map_positions_to_interests(self, request: PositionMapRequest) -> list[AIPositionLinkDraft]:
        if not request.positions:
            return []
        response = self._client.responses.parse(
            model=self._config.openai_model,
            instructions=_load_prompt("map_positions_to_interests.md"),
            input=[{"role": "user", "content": _format_position_map_request(request)}],
            text_format=AIPositionLinkBatch,
            **self._config.response_kwargs(),
        )
        batch = response.output_parsed
        if batch is None:
            raise RuntimeError("OpenAI returned no parsed position-interest links")
        return batch.links

    def map_agreement_landscape(self, request: AgreementRequest) -> list[AIAgreementItemDraft]:
        conflicts_text = "\n".join(f"- id={c.id}: {c.field_description}" for c in request.conflicts)
        content = f"{request.context}\n\nExisting conflicts:\n{conflicts_text}"
        response = self._client.responses.parse(
            model=self._config.openai_model,
            instructions=_load_prompt("map_agreement_landscape.md"),
            input=[{"role": "user", "content": content}],
            text_format=AIAgreementBatch,
            **self._config.response_kwargs(),
        )
        batch = response.output_parsed
        if batch is None:
            raise RuntimeError("OpenAI returned no parsed agreement landscape")
        return batch.items

    def analyze_walk_away(self, request: WalkAwayRequest) -> AIWalkAwayDraft:
        response = self._client.responses.parse(
            model=self._config.openai_model,
            instructions=_load_prompt("analyze_walk_away.md"),
            input=[{"role": "user", "content": request.context}],
            text_format=AIWalkAwayDraft,
            **self._config.response_kwargs(),
        )
        draft = response.output_parsed
        if draft is None:
            raise RuntimeError("OpenAI returned no parsed walk-away analysis")
        return draft

    def classify_constraints(self, request: ConstraintRequest) -> ConstraintClassificationDraft:
        content = f"Usable BATNA/reservation value exists: {request.has_batna}\n\n{request.context}"
        response = self._client.responses.parse(
            model=self._config.openai_model,
            instructions=_load_prompt("classify_constraints.md"),
            input=[{"role": "user", "content": content}],
            text_format=ConstraintClassificationDraft,
            **self._config.response_kwargs(),
        )
        draft = response.output_parsed
        if draft is None:
            raise RuntimeError("OpenAI returned no parsed constraint classification")
        return draft

    def generate_options(self, request: OptionRequest) -> list[AIOptionDraft]:
        response = self._client.responses.parse(
            model=self._config.openai_model,
            instructions=_load_prompt("generate_options.md"),
            input=[{"role": "user", "content": _format_option_request(request)}],
            text_format=OptionBatch,
            **self._config.response_kwargs(),
        )
        batch = response.output_parsed
        if batch is None:
            raise RuntimeError("OpenAI returned no parsed options")
        return batch.options

    def build_haggle_plan(self, request: HaggleRequest) -> HagglePlanDraft:
        response = self._client.responses.parse(
            model=self._config.openai_model,
            instructions=_load_prompt("build_haggle_plan.md"),
            input=[{"role": "user", "content": _format_haggle_request(request)}],
            text_format=HagglePlanDraft,
            **self._config.response_kwargs(),
        )
        draft = response.output_parsed
        if draft is None:
            raise RuntimeError("OpenAI returned no parsed haggle plan")
        return draft

    def generate_brief(self, request: BriefRequest) -> BriefProseDraft:
        response = self._client.responses.parse(
            model=self._config.openai_model,
            instructions=_load_prompt("generate_brief.md"),
            input=[{"role": "user", "content": _format_brief_request(request.case)}],
            text_format=BriefProseDraft,
            **self._config.response_kwargs(),
        )
        draft = response.output_parsed
        if draft is None:
            raise RuntimeError("OpenAI returned no parsed brief prose")
        return draft

    def phrase_in_english(self, request: PhraseInEnglishRequest) -> list[AIEnglishVariantDraft]:
        response = self._client.responses.parse(
            model=self._config.openai_model,
            instructions=_load_prompt("phrase_in_english.md"),
            input=[{"role": "user", "content": _format_language_request(request.draft_request, request.context)}],
            text_format=AIEnglishPhraseBatch,
            **self._config.response_kwargs(),
        )
        batch = response.output_parsed
        if batch is None:
            raise RuntimeError("OpenAI returned no parsed English phrasing")
        return batch.variants

    def draft_bilingual_reply(self, request: BilingualReplyRequest) -> AIBilingualReplyDraft:
        response = self._client.responses.parse(
            model=self._config.openai_model,
            instructions=_load_prompt("draft_bilingual_reply.md"),
            input=[{"role": "user", "content": _format_language_request(request.draft_request, request.context)}],
            text_format=AIBilingualReplyDraft,
            **self._config.response_kwargs(),
        )
        draft = response.output_parsed
        if draft is None:
            raise RuntimeError("OpenAI returned no parsed bilingual reply")
        return draft


def _format_language_request(request: LanguageDraftRequest, context: str) -> str:
    lines = [
        f"Mode: {request.mode}",
        f"Input language: {request.input_language}",
        f"Tone: {request.tone}",
    ]
    if request.intent:
        lines.append(f"Intent: {request.intent}")
    if request.protected_terms:
        lines.append("Protected terms (honor verbatim): " + ", ".join(request.protected_terms))
    if request.do_not_disclose:
        lines.append("Do not disclose: " + ", ".join(request.do_not_disclose))
    lines.append(f"\nUser input:\n{request.user_input}")
    if context:
        lines.append(f"\nConfirmed context:\n{context}")
    return "\n".join(lines)


def _format_brief_request(case: NegotiationCase) -> str:
    lines = []
    if case.my_role and case.my_role.current_value:
        lines.append(f"My role: {case.my_role.current_value}")
    if case.counterpart_role and case.counterpart_role.current_value:
        lines.append(f"Counterpart role: {case.counterpart_role.current_value}")
    if case.objective and case.objective.current_value:
        lines.append(f"Objective: {case.objective.current_value}")
    for issue in case.issues:
        target = issue.target.current_value if issue.target and issue.target.current_value else "unknown"
        lines.append(f"Issue: {issue.title} (target: {target})")

    analysis = case.analysis
    if analysis:
        shared = [a for a in analysis.agreement_landscape if a.standing == "shared"]
        if shared:
            lines.append("\nShared facts/values (islands of agreement):")
            for item in shared:
                lines.append(f"- {item.statement}")

        questions = [
            a.verification_question for a in analysis.agreement_landscape if a.verification_question
        ] + [q.question for q in case.open_questions]
        if questions:
            lines.append("\nCandidate questions:")
            for q in questions:
                lines.append(f"- {q}")

    return "\n".join(lines)


def _format_haggle_request(request: HaggleRequest) -> str:
    lines = [request.context, "\nOptions:"]
    for option in request.options:
        lines.append(f"- id={option.id} [{option.option_type}] {option.title}: {option.description}")
    lines.append("\nTrade currencies:")
    for tc in request.trade_currencies:
        lines.append(f"- ({tc.direction}) {tc.item}: cost_to_me={tc.cost_to_me}, value_to_them={tc.value_to_them_hypothesis}")
    return "\n".join(lines)


def _format_option_request(request: OptionRequest) -> str:
    lines = [request.context, "\nInterests:"]
    for interest in request.interests:
        lines.append(f"- id={interest.id} party={interest.party} category={interest.category}: {interest.statement.current_value!r}")
    if request.existing_option_titles:
        lines.append("\nAlready-generated options (avoid pure repeats, but do not remove or restate them):")
        for title in request.existing_option_titles:
            lines.append(f"- {title}")
    return "\n".join(lines)


def _format_position_map_request(request: PositionMapRequest) -> str:
    lines = ["Interests:"]
    for interest in request.interests:
        lines.append(f"- id={interest.id} party={interest.party} category={interest.category}: {interest.statement.current_value!r}")
    lines.append("\nPositions:")
    for position in request.positions:
        lines.append(f"- ref={position.ref} party={position.party}: {position.statement.current_value!r}")
    return "\n".join(lines)


def _format_consolidation_request(request: ConsolidationRequest) -> str:
    lines = ["Issues:"]
    for extraction in request.extractions:
        for issue in extraction.issues:
            lines.append(f"- ref={extraction.document_id}:{issue.id} title={issue.title!r}")
    return "\n".join(lines)


def _format_organization_request(request: MaterialOrganizationRequest) -> str:
    lines = ["Documents:"]
    for doc in request.documents:
        lines.append(f"- {doc.document_id}: filename={doc.filename!r}, upload_index={doc.upload_index}")

    lines.append("\nCues:")
    for cue in request.cues:
        location = f"page {cue.page_number}" if cue.page_number is not None else f"paragraph {cue.paragraph_id}"
        lines.append(
            f"- [{cue.document_id}] {cue.cue_type} ({location}): "
            f"{cue.normalized_value!r} — \"{cue.excerpt}\""
        )
    return "\n".join(lines)


def _format_unit(unit: TextUnit) -> str:
    label = f"page {unit.page_number}" if unit.page_number is not None else f"paragraph {unit.paragraph_id}"
    return f"[{label}]\n{unit.text}"
