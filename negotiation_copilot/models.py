"""Core Pydantic models (SPEC §5.4, §6.4, §9, §11.4).

Field order in each class follows the SPEC where the SPEC gives one verbatim.
Models the SPEC calls "retained from v1" but does not print (Evidence,
ReviewedText, DocumentRecord, NegotiationIssue, Constraint, Deadline,
Conflict, OpenQuestion) are reconstructed here from their usages elsewhere in
the SPEC; see docs/DECISIONS.md for the reasoning.
"""

from datetime import datetime
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator

EpistemicStatus = Literal["explicit", "inferred", "unknown", "user_confirmed"]
MaterialScope = Literal["my_confidential", "shared", "instructor_rules"]


def _new_id() -> str:
    return uuid4().hex


# ---------------------------------------------------------------------------
# Shared building blocks
# ---------------------------------------------------------------------------


class Evidence(BaseModel):
    document_id: str
    page_number: int | None = None
    paragraph_id: str | None = None
    excerpt: str


class ReviewedText(BaseModel):
    """A textual claim with epistemic status, evidence, and user-edit tracking.

    `current_value` is what the app displays and lets the user edit;
    `ai_original_value` is preserved untouched so edits are always reversible.
    """

    current_value: str | None = None
    ai_original_value: str | None = None
    evidence_status: EpistemicStatus = "unknown"
    evidence: list[Evidence] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# §4.1 Material management
# ---------------------------------------------------------------------------

FileType = Literal["pdf", "docx", "txt", "md", "pasted_text"]
ProcessingStatus = Literal["pending", "processing", "processed", "failed"]


class ParagraphRecord(BaseModel):
    document_id: str
    paragraph_id: str
    index: int
    text: str


class DocumentRecord(BaseModel):
    document_id: str = Field(default_factory=_new_id)
    filename: str
    upload_index: int
    file_type: FileType
    size_bytes: int
    sha256: str
    page_count: int | None = None
    paragraph_count: int | None = None
    parse_method: str | None = None
    page_reading_methods: dict[int, str] = Field(default_factory=dict)
    pages_needing_review: list[int] = Field(default_factory=list)
    scope: MaterialScope
    processing_status: ProcessingStatus = "pending"
    warnings: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# §5.4 Unified PDF reading structure
# ---------------------------------------------------------------------------


class PDFPageResult(BaseModel):
    document_id: str
    page_number: int
    reading_method: Literal["native_text", "ai_pdf", "ai_vision"]
    content: str
    key_items: list[str] = Field(default_factory=list)
    quality_flags: list[str] = Field(default_factory=list)
    status: Literal["success", "needs_review", "failed"]
    error_type: str | None = None


class TextUnit(BaseModel):
    """One paragraph (DOCX/TXT/MD/pasted) or one PDF page, normalized so any
    text-consuming stage (cue extraction, extraction, summarization) can work
    the same way regardless of the source format."""

    document_id: str
    page_number: int | None = None
    paragraph_id: str | None = None
    text: str


# ---------------------------------------------------------------------------
# §6.4 Material relationships and conditional chronology
# ---------------------------------------------------------------------------


class RelationshipCue(BaseModel):
    document_id: str
    cue_type: Literal["date", "relative_time", "version", "cross_reference", "topic", "document_role"]
    normalized_value: str | None
    excerpt: str
    page_number: int | None = None
    paragraph_id: str | None = None


class DocumentRelation(BaseModel):
    source_document_id: str
    target_document_id: str | None
    relation_type: Literal["before", "after", "version_of", "references", "same_topic", "complements", "independent"]
    explanation: str
    evidence: list[Evidence]
    confidence: Literal["high", "medium", "low"]


class DocumentGroup(BaseModel):
    name: str
    document_ids: list[str]
    organizing_reason: str


class MaterialOrganizationResult(BaseModel):
    organization_mode: Literal["chronological", "versioned", "thematic", "complementary", "independent", "mixed"]
    temporal_order_applicable: bool
    proposed_order: list[str] | None
    confirmed_order: list[str] | None
    groups: list[DocumentGroup] = Field(default_factory=list)
    relations: list[DocumentRelation] = Field(default_factory=list)
    confidence: Literal["high", "medium", "low"] = "low"
    rationale: str = ""  # short user-facing rationale (SPEC §6.2); no hidden reasoning stored
    unresolved_ambiguities: list[str] = Field(default_factory=list)
    review_status: Literal["unreviewed", "confirmed", "edited_by_user"] = "unreviewed"


# ---------------------------------------------------------------------------
# §7 Summaries, extraction, consolidation (v1, retained)
# ---------------------------------------------------------------------------


class NegotiationIssue(BaseModel):
    id: str = Field(default_factory=_new_id)
    title: str
    my_position: ReviewedText | None = None
    counterpart_position: ReviewedText | None = None
    target: ReviewedText | None = None
    acceptable_range: ReviewedText | None = None
    priority: Literal["high", "medium", "low", "unknown"] = "unknown"
    flexibility: Literal["flexible", "firm", "unknown"] = "unknown"
    status: Literal["open", "resolved", "dropped"] = "open"
    evidence: list[Evidence] = Field(default_factory=list)


class Constraint(BaseModel):
    """A raw candidate limit pulled from materials, before §8.5 classifies it
    into a Redline or a Bottomline."""

    id: str = Field(default_factory=_new_id)
    statement: ReviewedText
    source_type: Literal["instructor_rules", "authority_limit", "legal_ethical", "principal_mandate", "unknown"] = "unknown"
    issue_id: str | None = None
    evidence: list[Evidence] = Field(default_factory=list)


class Deadline(BaseModel):
    id: str = Field(default_factory=_new_id)
    description: str
    date_text: str | None = None
    normalized_date: str | None = None
    evidence: list[Evidence] = Field(default_factory=list)


class ConflictingValue(BaseModel):
    document_id: str
    value: str
    evidence: Evidence


class Conflict(BaseModel):
    id: str = Field(default_factory=_new_id)
    field_description: str
    values: list[ConflictingValue]
    resolution_status: Literal["unresolved", "resolved_by_user"] = "unresolved"
    resolution_note: str | None = None


class OpenQuestion(BaseModel):
    id: str = Field(default_factory=_new_id)
    question: str
    context: str | None = None
    related_document_ids: list[str] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)


class SummaryBullet(BaseModel):
    text: str
    evidence: Evidence


class DocumentSummary(BaseModel):
    bullets: list[SummaryBullet]  # 3-6, each linked back to its page/paragraph
    role_and_purpose: str | None = None
    relationship_to_others: str | None = None
    warnings: list[str] = Field(default_factory=list)


class DocumentExtraction(BaseModel):
    """Per-document machine-readable extraction (SPEC §7.2), produced before
    cross-document consolidation (§7.3) merges these into a NegotiationCase."""

    document_id: str
    summary: DocumentSummary
    my_role: ReviewedText | None = None
    counterpart_role: ReviewedText | None = None
    context: ReviewedText | None = None
    objective: ReviewedText | None = None
    interests: list[ReviewedText] = Field(default_factory=list)
    positions: list[ReviewedText] = Field(default_factory=list)
    batna: ReviewedText | None = None
    issues: list[NegotiationIssue] = Field(default_factory=list)
    targets: list[ReviewedText] = Field(default_factory=list)
    hard_constraints: list[Constraint] = Field(default_factory=list)
    authority_limits: list[ReviewedText] = Field(default_factory=list)
    deadlines: list[Deadline] = Field(default_factory=list)
    possible_concessions: list[ReviewedText] = Field(default_factory=list)
    counterpart_information: list[ReviewedText] = Field(default_factory=list)
    open_questions: list[OpenQuestion] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# §9 Negotiation analysis layer
# ---------------------------------------------------------------------------


class InterestItem(BaseModel):
    id: str = Field(default_factory=_new_id)
    party: Literal["me", "counterpart"]
    category: Literal["need", "fear", "motive", "value"]
    statement: ReviewedText
    verification_question: str | None = None
    is_hypothesis: bool = False  # always True for counterpart


class PositionInterestLink(BaseModel):
    id: str = Field(default_factory=_new_id)
    party: Literal["me", "counterpart"]
    stated_position: ReviewedText
    underlying_interest_ids: list[str]
    inference_basis: str
    reframe_question: str | None = None
    misalignment_note: str | None = None


class AgreementItem(BaseModel):
    id: str = Field(default_factory=_new_id)
    kind: Literal["fact", "value", "process"]
    statement: str
    standing: Literal["shared", "contested", "unverified"]
    my_view: str | None = None
    counterpart_view: str | None = None
    conflict_id: str | None = None
    verification_question: str | None = None
    evidence: list[Evidence] = Field(default_factory=list)


class WalkAwayAnalysis(BaseModel):
    my_batna: ReviewedText
    batna_quality: Literal["strong", "moderate", "weak", "unknown"]
    quality_rationale: str
    actions_to_improve_batna: list[str] = Field(default_factory=list)
    estimated_reservation_value: ReviewedText | None
    reservation_derivation: str | None
    counterpart_batna_hypothesis: ReviewedText | None
    tests_to_probe_their_batna: list[str] = Field(default_factory=list)
    walk_away_triggers: list[str] = Field(default_factory=list)
    exit_script: str
    do_not_disclose: list[str] = Field(default_factory=list)


class Redline(BaseModel):
    id: str = Field(default_factory=_new_id)
    statement: ReviewedText
    source_type: Literal["instructor_rules", "authority_limit", "legal_ethical", "principal_mandate"]
    consequence_if_crossed: str
    confirmed_by_user: bool = False
    evidence: list[Evidence] = Field(default_factory=list)


class Bottomline(BaseModel):
    id: str = Field(default_factory=_new_id)
    issue_id: str | None
    threshold_value: ReviewedText  # keep units as text; do not force float
    direction: Literal["min", "max"]
    rationale: str
    linked_batna_reference: str | None
    risk_if_crossed: str
    revisit_conditions: list[str] = Field(default_factory=list)
    provisional: bool = True  # False only when BATNA-linked and confirmed
    confirmed_by_user: bool = False
    evidence: list[Evidence] = Field(default_factory=list)


class NegotiationOption(BaseModel):
    id: str = Field(default_factory=_new_id)
    title: str
    description: str
    option_type: Literal[
        "valuation", "time", "risk", "capability", "unbundle", "add_issue", "non_monetary", "process"
    ]
    serves_my_interest_ids: list[str]
    serves_their_interest_ids: list[str]
    cost_to_me: Literal["low", "medium", "high", "unknown"]
    value_to_them_hypothesis: Literal["low", "medium", "high", "unknown"]
    depends_on: list[str] = Field(default_factory=list)
    evidence_status: EpistemicStatus
    status: Literal["idea", "viable", "rejected"] = "idea"


class TradeCurrency(BaseModel):
    item: str
    cost_to_me: Literal["low", "medium", "high", "unknown"]
    value_to_them_hypothesis: Literal["low", "medium", "high", "unknown"]
    direction: Literal["i_can_give", "i_want_to_get"]


class TradePackage(BaseModel):
    id: str = Field(default_factory=_new_id)
    label: str
    option_ids: list[str]
    what_i_give: list[str]
    what_i_get: list[str]
    equivalence_note: str
    validator_warnings: list[str] = Field(default_factory=list)


class ConcessionStep(BaseModel):
    order: int
    issue_id: str | None
    from_value: str
    to_value: str
    ask_in_return: str  # never empty — every concession is reciprocal (SPEC §8.7)
    trigger_condition: str

    @field_validator("ask_in_return")
    @classmethod
    def _ask_in_return_not_empty(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("ask_in_return must not be empty — a concession step can never be unconditional")
        return value


class CounterTactic(BaseModel):
    tactic: str
    response_line: str


class HagglePlan(BaseModel):
    anchor: str
    justification_standard: str  # objective criterion; required — an anchor without one is invalid (SPEC §8.7)
    trade_currencies: list[TradeCurrency] = Field(default_factory=list)
    packages: list[TradePackage] = Field(default_factory=list)
    concession_ladder: list[ConcessionStep] = Field(default_factory=list)
    counter_tactics: list[CounterTactic] = Field(default_factory=list)
    validator_warnings: list[str] = Field(default_factory=list)

    @field_validator("justification_standard")
    @classmethod
    def _justification_standard_not_empty(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("justification_standard must not be empty — an anchor without one is invalid")
        return value


class NegotiationAnalysis(BaseModel):
    interests: list[InterestItem] = Field(default_factory=list)
    position_links: list[PositionInterestLink] = Field(default_factory=list)
    agreement_landscape: list[AgreementItem] = Field(default_factory=list)
    walk_away: WalkAwayAnalysis | None = None
    redlines: list[Redline] = Field(default_factory=list)
    bottomlines: list[Bottomline] = Field(default_factory=list)
    options: list[NegotiationOption] = Field(default_factory=list)
    haggle_plan: HagglePlan | None = None
    generation_notes: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# §7.2 / consolidated case (v1, retained; gains `analysis` per §9)
# ---------------------------------------------------------------------------


class NegotiationCase(BaseModel):
    case_id: str = Field(default_factory=_new_id)
    documents: list[DocumentRecord] = Field(default_factory=list)
    relationship_cues: list[RelationshipCue] = Field(default_factory=list)
    document_extractions: list[DocumentExtraction] = Field(default_factory=list)
    organization: MaterialOrganizationResult | None = None

    my_role: ReviewedText | None = None
    counterpart_role: ReviewedText | None = None
    context: ReviewedText | None = None
    objective: ReviewedText | None = None

    interests: list[ReviewedText] = Field(default_factory=list)
    positions: list[ReviewedText] = Field(default_factory=list)
    batna: ReviewedText | None = None
    issues: list[NegotiationIssue] = Field(default_factory=list)
    targets: list[ReviewedText] = Field(default_factory=list)
    hard_constraints: list[Constraint] = Field(default_factory=list)
    authority_limits: list[ReviewedText] = Field(default_factory=list)
    deadlines: list[Deadline] = Field(default_factory=list)
    possible_concessions: list[ReviewedText] = Field(default_factory=list)
    counterpart_information: list[ReviewedText] = Field(default_factory=list)

    open_questions: list[OpenQuestion] = Field(default_factory=list)
    conflicts: list[Conflict] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    analysis: NegotiationAnalysis | None = None


# ---------------------------------------------------------------------------
# §11.4 Live workspace and language assistant
# ---------------------------------------------------------------------------


class BriefNote(BaseModel):
    id: str = Field(default_factory=_new_id)
    section_id: str
    note_type: Literal["my_judgment", "live_note"]
    text: str
    created_at: datetime
    updated_at: datetime


class BriefSectionState(BaseModel):
    section_id: str
    title: str
    ai_generated_base: str
    evidence: list[Evidence] = Field(default_factory=list)
    status: Literal["confirmed", "tentative", "needs_verification", "no_longer_relevant"] = "tentative"
    pinned: bool = False
    stale: bool = False
    source_fingerprint: str | None = None  # hash of the case/analysis data this section was built from
    notes: list[BriefNote] = Field(default_factory=list)


class LanguageDraftRequest(BaseModel):
    mode: Literal["chinese_to_english", "reply_to_counterpart"]
    user_input: str
    input_language: Literal["zh", "en", "mixed", "auto"]
    intent: str | None = None
    tone: Literal["collaborative", "neutral", "firm"]
    selected_brief_section_ids: list[str] = Field(default_factory=list)
    protected_terms: list[str] = Field(default_factory=list)
    do_not_disclose: list[str] = Field(default_factory=list)


class EnglishPhraseVariant(BaseModel):
    label: Literal["natural", "collaborative", "firm"]
    english_draft: str
    chinese_back_translation: str
    risk_flags: list[str] = Field(default_factory=list)


class BilingualReplyDraft(BaseModel):
    counterpart_summary_zh: str | None
    counterpart_summary_en: str | None
    points_to_verify: list[str] = Field(default_factory=list)
    chinese_draft: str
    english_draft: str
    risk_flags: list[str] = Field(default_factory=list)


class LiveInteraction(BaseModel):
    id: str = Field(default_factory=_new_id)
    created_at: datetime
    mode: Literal["chinese_to_english", "reply_to_counterpart"]
    user_input: str
    selected_brief_section_ids: list[str] = Field(default_factory=list)
    output: dict
    saved_note_id: str | None = None


class NegotiationBrief(BaseModel):
    """The Prep Brief (SPEC §10.2): 18 BriefSectionState entries, one per
    named section, generated from confirmed data only."""

    sections: list[BriefSectionState] = Field(default_factory=list)
    generation_notes: list[str] = Field(default_factory=list)


class LiveCard(BaseModel):
    """Compressed view for live use (SPEC §10.1): same data source as the
    Prep Brief, hard-capped so it fits on one screen with no long scrolling."""

    walk_away_line: str
    redlines: list[str] = Field(default_factory=list)
    my_top_interests: list[str] = Field(default_factory=list)
    their_top_interests: list[str] = Field(default_factory=list)
    shared_facts_opener: list[str] = Field(default_factory=list)
    packages: list[str] = Field(default_factory=list)
    next_questions: list[str] = Field(default_factory=list)
    pinned_sections: list[BriefSectionState] = Field(default_factory=list)


class LiveWorkspaceState(BaseModel):
    brief_sections: list[BriefSectionState] = Field(default_factory=list)
    interaction_history: list[LiveInteraction] = Field(default_factory=list)
