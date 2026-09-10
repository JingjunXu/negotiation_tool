"""FakeAIClient: deterministic stand-in for OpenAIClient when no API key is
present. It must be as honest as the real client — never inventing content
for a page it did not (and, being fake, cannot) actually read.
"""

import hashlib
import logging
import re
from datetime import datetime
from pathlib import Path

from .ai_client import (
    AgreementRequest,
    AIAgreementItemDraft,
    AIBilingualReplyDraft,
    AIConcessionStepDraft,
    AIEnglishVariantDraft,
    AIOptionDraft,
    AIPackageDraft,
    AIPageReading,
    AIPositionLinkDraft,
    AIRedlineDraft,
    AIReviewedText,
    AIWalkAwayDraft,
    BilingualReplyRequest,
    BriefProseDraft,
    BriefRequest,
    ConsolidationPlan,
    ConsolidationRequest,
    ConstraintClassificationDraft,
    ConstraintRequest,
    ExtractionRequest,
    HaggleRequest,
    HagglePlanDraft,
    InterestRequest,
    IssueGroupDraft,
    MaterialOrganizationRequest,
    OptionRequest,
    PhraseInEnglishRequest,
    PositionMapRequest,
    ReadPDFRequest,
    RelationshipCueRequest,
    WalkAwayRequest,
)
from .models import (
    CounterTactic,
    Deadline,
    DocumentExtraction,
    DocumentGroup,
    DocumentRelation,
    DocumentSummary,
    Evidence,
    InterestItem,
    MaterialOrganizationResult,
    OpenQuestion,
    PDFPageResult,
    RelationshipCue,
    SummaryBullet,
    TextUnit,
)

logger = logging.getLogger(__name__)

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "tests" / "fixtures"

# Deterministic canned "readings" for checked-in PDF fixtures (SPEC §5.5),
# keyed by filename here and re-keyed by content hash at load time. Anything
# a user actually uploads in fake mode will not match one of these and falls
# through to an honest "not actually read" placeholder.
_FIXTURE_MANIFEST: dict[str, dict[int, AIPageReading]] = {
    "sample_native_and_blank.pdf": {
        2: AIPageReading(
            page_number=2,
            content="Contract value: $85,000 due within 45 days of signing.",
            key_items=["$85,000", "45 days"],
            quality_flags=[],
            status="success",
        ),
    },
}


def _load_fixture_readings() -> dict[str, dict[int, AIPageReading]]:
    readings_by_hash: dict[str, dict[int, AIPageReading]] = {}
    for filename, pages in _FIXTURE_MANIFEST.items():
        path = FIXTURES_DIR / filename
        if not path.exists():
            logger.warning("FakeAIClient fixture %s is missing from %s", filename, FIXTURES_DIR)
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        readings_by_hash[digest] = pages
    return readings_by_hash


_FIXTURE_READINGS = _load_fixture_readings()

# Relationship-cue heuristics (SPEC §6.2 phase A). Unlike PDF reading, this
# stage works on text we already faithfully extracted, so a rule-based
# implementation can run on *any* real input honestly: it only ever reports
# a match it can point to in `text`, never a claim it made up.
_MONTHS = (
    "January|February|March|April|May|June|July|August|September|October|November|December"
)
_DATE_PATTERNS = [
    re.compile(rf"\b(?:{_MONTHS})\s+\d{{1,2}}(?:st|nd|rd|th)?,?\s+\d{{4}}\b"),
    re.compile(rf"\b\d{{1,2}}\s+(?:{_MONTHS})\s+\d{{4}}\b"),
    re.compile(r"\b\d{4}-\d{2}-\d{2}\b"),
    re.compile(r"\b\d{1,2}/\d{1,2}/\d{2,4}\b"),
]
_RELATIVE_TIME_PHRASES = [
    "yesterday", "last week", "last month", "next week", "next month",
    "prior to", "following the", "the following day", "the previous day",
    "earlier that", "a week later", "two days later", "in the coming days",
    "by the end of",
]
_VERSION_PATTERNS = [
    re.compile(r"\b(draft|final|revised|amended)\b", re.IGNORECASE),
    re.compile(r"\bv(?:ersion)?\s?\d+(?:\.\d+)?\b", re.IGNORECASE),
]
_CROSS_REFERENCE_PATTERNS = [
    re.compile(r"\bDocument\s+\d+\b", re.IGNORECASE),
    re.compile(r"\bsee attached\b", re.IGNORECASE),
    re.compile(r"\bas discussed in\b", re.IGNORECASE),
    re.compile(r"\breferenced in\b", re.IGNORECASE),
    re.compile(r"\bin response to\b", re.IGNORECASE),
]
_DOCUMENT_ROLE_KEYWORDS = {
    "minutes": "meeting minutes",
    "meeting": "meeting notes",
    "news article": "news article",
    "statement": "statement",
    "post": "social media post",
    "report": "report",
    "letter": "letter",
    "email": "email",
    "podcast": "podcast",
}


def _excerpt_window(text: str, start: int, end: int, *, radius: int = 30) -> str:
    return text[max(0, start - radius) : min(len(text), end + radius)].strip()


def _heuristic_cues_for_unit(document_id: str, page_number, paragraph_id, text: str) -> list[RelationshipCue]:
    cues: list[RelationshipCue] = []

    for pattern in _DATE_PATTERNS:
        for match in pattern.finditer(text):
            cues.append(
                RelationshipCue(
                    document_id=document_id,
                    cue_type="date",
                    normalized_value=match.group(0),
                    excerpt=_excerpt_window(text, match.start(), match.end()),
                    page_number=page_number,
                    paragraph_id=paragraph_id,
                )
            )

    lowered = text.lower()
    for phrase in _RELATIVE_TIME_PHRASES:
        index = lowered.find(phrase)
        if index != -1:
            cues.append(
                RelationshipCue(
                    document_id=document_id,
                    cue_type="relative_time",
                    normalized_value=phrase,
                    excerpt=_excerpt_window(text, index, index + len(phrase)),
                    page_number=page_number,
                    paragraph_id=paragraph_id,
                )
            )

    for pattern in _VERSION_PATTERNS:
        for match in pattern.finditer(text):
            cues.append(
                RelationshipCue(
                    document_id=document_id,
                    cue_type="version",
                    normalized_value=match.group(0).lower(),
                    excerpt=_excerpt_window(text, match.start(), match.end()),
                    page_number=page_number,
                    paragraph_id=paragraph_id,
                )
            )

    for pattern in _CROSS_REFERENCE_PATTERNS:
        for match in pattern.finditer(text):
            cues.append(
                RelationshipCue(
                    document_id=document_id,
                    cue_type="cross_reference",
                    normalized_value=match.group(0),
                    excerpt=_excerpt_window(text, match.start(), match.end()),
                    page_number=page_number,
                    paragraph_id=paragraph_id,
                )
            )

    return cues


def _heuristic_document_role_cue(document_id: str, units) -> RelationshipCue | None:
    for unit in units:
        lowered = unit.text.lower()
        for keyword, normalized in _DOCUMENT_ROLE_KEYWORDS.items():
            index = lowered.find(keyword)
            if index != -1:
                return RelationshipCue(
                    document_id=document_id,
                    cue_type="document_role",
                    normalized_value=normalized,
                    excerpt=_excerpt_window(unit.text, index, index + len(keyword)),
                    page_number=unit.page_number,
                    paragraph_id=unit.paragraph_id,
                )
    return None


# Material organization heuristics (SPEC §6.2 phase B). Works purely from
# already-extracted cues (never from filenames — SPEC: "filenames never
# override body text"), so it is honest even on documents it never "read".
_DATE_FORMATS = ["%B %d, %Y", "%B %d %Y", "%d %B %Y", "%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y"]
_VERSION_RANK = {"draft": 0, "revised": 1, "amended": 1, "final": 2}


def _parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    cleaned = re.sub(r"(\d)(st|nd|rd|th)\b", r"\1", value.strip())
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(cleaned, fmt)
        except ValueError:
            continue
    return None


def _earliest_date(cues: list[RelationshipCue]) -> datetime | None:
    dates = [d for c in cues if c.cue_type == "date" and (d := _parse_date(c.normalized_value)) is not None]
    return min(dates) if dates else None


def _version_rank(cues: list[RelationshipCue]) -> int | None:
    ranks = [_VERSION_RANK[c.normalized_value] for c in cues if c.cue_type == "version" and c.normalized_value in _VERSION_RANK]
    return max(ranks) if ranks else None


def _document_role(cues: list[RelationshipCue]) -> str | None:
    for cue in cues:
        if cue.cue_type == "document_role":
            return cue.normalized_value
    return None


def _classify_organization(request: MaterialOrganizationRequest) -> MaterialOrganizationResult:
    document_ids = [doc.document_id for doc in request.documents]
    cues_by_doc: dict[str, list[RelationshipCue]] = {doc_id: [] for doc_id in document_ids}
    for cue in request.cues:
        cues_by_doc.setdefault(cue.document_id, []).append(cue)

    dates_by_doc = {doc_id: _earliest_date(cues) for doc_id, cues in cues_by_doc.items()}
    dated_doc_ids = [doc_id for doc_id, date in dates_by_doc.items() if date is not None]

    if len(dated_doc_ids) >= 2:
        ordered = sorted(dated_doc_ids, key=lambda doc_id: dates_by_doc[doc_id])
        distinct_dates = len({dates_by_doc[d] for d in dated_doc_ids}) == len(dated_doc_ids)
        undated_doc_ids = [d for d in document_ids if d not in dated_doc_ids]

        if not undated_doc_ids:
            confidence = "high" if distinct_dates else "medium"
            return MaterialOrganizationResult(
                organization_mode="chronological",
                temporal_order_applicable=True,
                proposed_order=ordered,
                confirmed_order=None,
                groups=[],
                relations=_before_after_relations(ordered),
                confidence=confidence,
                rationale="Every document carries an explicit date cue; ordered earliest to latest by body text.",
                unresolved_ambiguities=[] if distinct_dates else ["Two or more documents share the same extracted date."],
                review_status="unreviewed",
            )

        # Mixed: real dated evidence for some documents, none for the rest.
        confidence = "medium" if len(dated_doc_ids) >= len(undated_doc_ids) else "low"
        return MaterialOrganizationResult(
            organization_mode="mixed",
            temporal_order_applicable=True,
            proposed_order=ordered,
            confirmed_order=None,
            groups=[DocumentGroup(name="Undated materials", document_ids=undated_doc_ids, organizing_reason="No date cue found in body text")],
            relations=_before_after_relations(ordered),
            confidence=confidence,
            rationale="Only some documents carry a dated cue; the rest have no temporal evidence and are grouped separately.",
            unresolved_ambiguities=[f"No date evidence for: {', '.join(undated_doc_ids)}"],
            review_status="unreviewed",
        )

    ranks_by_doc = {doc_id: _version_rank(cues) for doc_id, cues in cues_by_doc.items()}
    versioned_doc_ids = [doc_id for doc_id, rank in ranks_by_doc.items() if rank is not None]
    if len(versioned_doc_ids) >= 2:
        ordered = sorted(versioned_doc_ids, key=lambda doc_id: ranks_by_doc[doc_id])
        return MaterialOrganizationResult(
            organization_mode="versioned",
            temporal_order_applicable=True,
            proposed_order=ordered,
            confirmed_order=None,
            groups=[],
            relations=[
                DocumentRelation(source_document_id=b, target_document_id=a, relation_type="version_of", explanation="Version markers indicate a draft/revision/final lineage", evidence=[], confidence="medium")
                for a, b in zip(ordered, ordered[1:])
            ],
            confidence="medium",
            rationale="No dates were found, but draft/revised/final markers indicate a version lineage.",
            unresolved_ambiguities=[],
            review_status="unreviewed",
        )

    roles_by_doc = {doc_id: _document_role(cues) for doc_id, cues in cues_by_doc.items()}
    role_groups: dict[str, list[str]] = {}
    for doc_id, role in roles_by_doc.items():
        if role is not None:
            role_groups.setdefault(role, []).append(doc_id)
    if any(len(ids) >= 2 for ids in role_groups.values()):
        groups = [
            DocumentGroup(name=role.capitalize(), document_ids=ids, organizing_reason=f"Shared document role: {role}")
            for role, ids in role_groups.items()
        ]
        return MaterialOrganizationResult(
            organization_mode="thematic",
            temporal_order_applicable=False,
            proposed_order=None,
            confirmed_order=None,
            groups=groups,
            relations=[],
            confidence="medium",
            rationale="No temporal or version evidence; documents grouped by shared document role.",
            unresolved_ambiguities=[],
            review_status="unreviewed",
        )

    cross_refs = [c for c in request.cues if c.cue_type == "cross_reference"]
    if cross_refs:
        return MaterialOrganizationResult(
            organization_mode="complementary",
            temporal_order_applicable=False,
            proposed_order=None,
            confirmed_order=None,
            groups=[],
            relations=[
                DocumentRelation(source_document_id=c.document_id, target_document_id=None, relation_type="references", explanation=c.excerpt, evidence=[], confidence="low")
                for c in cross_refs
            ],
            confidence="low",
            rationale="Documents reference each other but carry no ordering evidence; treated as complementary.",
            unresolved_ambiguities=["Cross-references found but their target documents are not explicitly identified."],
            review_status="unreviewed",
        )

    return MaterialOrganizationResult(
        organization_mode="independent",
        temporal_order_applicable=False,
        proposed_order=None,
        confirmed_order=None,
        groups=[],
        relations=[],
        confidence="low",
        rationale="No temporal, version, thematic, or cross-reference evidence connects these documents.",
        unresolved_ambiguities=[],
        review_status="unreviewed",
    )


def _before_after_relations(ordered_doc_ids: list[str]) -> list[DocumentRelation]:
    return [
        DocumentRelation(
            source_document_id=earlier,
            target_document_id=later,
            relation_type="before",
            explanation="Earlier document's date cue precedes the later one's",
            evidence=[],
            confidence="medium",
        )
        for earlier, later in zip(ordered_doc_ids, ordered_doc_ids[1:])
    ]


_DEADLINE_KEYWORDS = ("deadline", "due", "by the", "must be completed", "no later than")
_MAX_SUMMARY_BULLETS = 6
_MAX_OPEN_QUESTIONS = 3


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", text.strip()) if s.strip()]


def _heuristic_extraction_for_document(document_id: str, units: list[TextUnit]) -> DocumentExtraction:
    """Honest fake extraction: surfaces only patterns actually present in the
    text (dates, questions, role keywords) — never a guessed objective,
    BATNA, or position, which would require real language understanding the
    fake client does not have. See docs/DECISIONS.md T3.4."""
    bullets: list[SummaryBullet] = []
    open_questions: list[OpenQuestion] = []
    deadlines: list[Deadline] = []

    for unit in units:
        cues = _heuristic_cues_for_unit(document_id, unit.page_number, unit.paragraph_id, unit.text)
        for cue in cues:
            if len(bullets) < _MAX_SUMMARY_BULLETS:
                bullets.append(
                    SummaryBullet(
                        text=f"{cue.cue_type}: {cue.excerpt}",
                        evidence=Evidence(
                            document_id=document_id, page_number=unit.page_number,
                            paragraph_id=unit.paragraph_id, excerpt=cue.excerpt,
                        ),
                    )
                )
            if cue.cue_type == "date":
                index = unit.text.find(cue.excerpt)
                window = unit.text[max(0, index - 60) : index + 60].lower() if index != -1 else ""
                if any(keyword in window for keyword in _DEADLINE_KEYWORDS):
                    deadlines.append(
                        Deadline(
                            description=cue.excerpt,
                            date_text=cue.normalized_value,
                            evidence=[
                                Evidence(
                                    document_id=document_id, page_number=unit.page_number,
                                    paragraph_id=unit.paragraph_id, excerpt=cue.excerpt,
                                )
                            ],
                        )
                    )

        if len(open_questions) < _MAX_OPEN_QUESTIONS:
            for question in _sentences(unit.text):
                if not question.endswith("?") or len(open_questions) >= _MAX_OPEN_QUESTIONS:
                    continue
                open_questions.append(
                    OpenQuestion(
                        question=question,
                        related_document_ids=[document_id],
                        evidence=[
                            Evidence(
                                document_id=document_id, page_number=unit.page_number,
                                paragraph_id=unit.paragraph_id, excerpt=question,
                            )
                        ],
                    )
                )

    if not bullets:
        for unit in units:
            if not unit.text.strip():
                continue
            for sentence in _sentences(unit.text)[:3]:
                bullets.append(
                    SummaryBullet(
                        text=sentence,
                        evidence=Evidence(
                            document_id=document_id, page_number=unit.page_number,
                            paragraph_id=unit.paragraph_id, excerpt=sentence,
                        ),
                    )
                )
            break

    role_cue = _heuristic_document_role_cue(document_id, units)
    role_and_purpose = f"Appears to be a {role_cue.normalized_value}." if role_cue else None

    summary = DocumentSummary(
        bullets=bullets[:_MAX_SUMMARY_BULLETS],
        role_and_purpose=role_and_purpose,
        relationship_to_others=None,
        warnings=[],
    )

    return DocumentExtraction(
        document_id=document_id,
        summary=summary,
        deadlines=deadlines,
        open_questions=open_questions,
    )


# Option-generation templates (SPEC §8.6). Unlike other fake-mode
# heuristics, genuine invention is exactly what this stage is for — SPEC's
# own vocabulary calls an Option "an invented possibility." These templates
# are generic (assert no fact about the case) and every one is linked to a
# real interest id, so nothing here violates "never invent negotiation
# content" (that rule is about facts, not brainstormed ideas).
_OPTION_TEMPLATES = [
    ("valuation", "Trade what is cheap for us for something the counterpart values more"),
    ("time", "Stage the commitment over time instead of one lump commitment"),
    ("risk", "Structure the term as contingent or performance-based to share risk"),
    ("capability", "Let each side contribute what it can deliver most cheaply"),
    ("unbundle", "Split the issue into smaller components negotiated separately"),
    ("add_issue", "Introduce an additional issue to trade across, widening the deal"),
    ("non_monetary", "Offer non-monetary value: recognition, information, precedent, or referrals"),
    ("process", "Add a process safeguard: a pilot period, review point, or renegotiation clause"),
]


def _fake_options(request: OptionRequest) -> list[AIOptionDraft]:
    my_ids = [i.id for i in request.interests if i.party == "me"]
    their_ids = [i.id for i in request.interests if i.party == "counterpart"]
    if not my_ids and not their_ids:
        return []  # nothing to honestly link an option to

    subject = "the negotiation"
    options = []
    for option_type, description in _OPTION_TEMPLATES:
        options.append(
            AIOptionDraft(
                title=f"{option_type.replace('_', ' ').capitalize()} option for {subject}",
                description=f"{description}, related to {subject}.",
                option_type=option_type,
                serves_my_interest_ids=my_ids[:1],
                serves_their_interest_ids=their_ids[:1],
                cost_to_me="unknown",
                value_to_them_hypothesis="unknown",
                depends_on=["Needs verification with the counterpart"],
                evidence_status="unknown",
            )
        )
    return options


class FakeAIClient:
    """AIClient implementation that never calls a network.

    `cache_tag` is distinct from any real OpenAIClient's tag so pdf_service's
    content cache never serves a fake "unread" placeholder after the user
    adds a real API key (or vice versa).
    """

    cache_tag = "fake"

    def read_pdf(self, request: ReadPDFRequest) -> list[PDFPageResult]:
        digest = hashlib.sha256(request.data).hexdigest()
        fixture_pages = _FIXTURE_READINGS.get(digest, {})

        results = []
        for page_number in request.page_numbers:
            reading = fixture_pages.get(page_number) or AIPageReading(
                page_number=page_number,
                content="",
                key_items=[],
                quality_flags=["fake_mode_no_ai_reading"],
                status="needs_review",
            )
            results.append(
                PDFPageResult(
                    document_id=request.document_id,
                    page_number=reading.page_number,
                    reading_method="ai_pdf",
                    content=reading.content,
                    key_items=reading.key_items,
                    quality_flags=reading.quality_flags,
                    status=reading.status,
                    error_type=reading.error_type,
                )
            )
        return results

    def extract_relationship_cues(self, request: RelationshipCueRequest) -> list[RelationshipCue]:
        cues: list[RelationshipCue] = []
        for unit in request.units:
            cues.extend(
                _heuristic_cues_for_unit(request.document_id, unit.page_number, unit.paragraph_id, unit.text)
            )
        role_cue = _heuristic_document_role_cue(request.document_id, request.units)
        if role_cue is not None:
            cues.append(role_cue)
        return cues

    def organize_materials(self, request: MaterialOrganizationRequest) -> MaterialOrganizationResult:
        return _classify_organization(request)

    def extract_document(self, request: ExtractionRequest) -> DocumentExtraction:
        return _heuristic_extraction_for_document(request.document_id, request.units)

    def consolidate_case(self, request: ConsolidationRequest) -> ConsolidationPlan:
        groups: dict[str, list[str]] = {}
        titles: dict[str, str] = {}
        for extraction in request.extractions:
            for issue in extraction.issues:
                key = re.sub(r"[^\w\s]", "", issue.title).strip().lower()
                ref = f"{extraction.document_id}:{issue.id}"
                groups.setdefault(key, []).append(ref)
                titles.setdefault(key, issue.title)
        return ConsolidationPlan(
            issue_groups=[IssueGroupDraft(issue_refs=refs, merged_title=titles[key]) for key, refs in groups.items()]
        )

    def analyze_interests(self, request: InterestRequest) -> list[InterestItem]:
        # Needs/fears/motives/values require real language understanding
        # this fake client does not have — inventing them would violate
        # "never invent negotiation content" (see docs/DECISIONS.md T4.1).
        # The one safe move: a hard constraint IS, by definition, something
        # that must be satisfied — relabeling it as a "need" reuses already-
        # evidenced content instead of guessing new content.
        return [
            InterestItem(
                party="me",
                category="need",
                statement=constraint.statement,
                is_hypothesis=False,
            )
            for constraint in request.my_hard_constraints
        ]

    def map_agreement_landscape(self, request: AgreementRequest) -> list[AIAgreementItemDraft]:
        # Judging shared-vs-contested-vs-unverified over free text needs real
        # comprehension; the one honest, non-fabricated signal available is
        # the case's already-detected Conflict records — each one *is* a
        # structurally verified disagreement, not a guess.
        return [
            AIAgreementItemDraft(
                kind="fact",
                statement=conflict.field_description,
                standing="contested",
                my_view=None,
                counterpart_view=None,
                conflict_id=conflict.id,
                verification_question=f"Please verify: {conflict.field_description}",
                evidence=[],
            )
            for conflict in request.conflicts
        ]

    def classify_constraints(self, request: ConstraintRequest) -> ConstraintClassificationDraft:
        # A constraint's source_type was already honestly extracted (T3.4);
        # only the four redline-eligible source types are safe to propose
        # mechanically here. Bottomlines need a direction and rationale —
        # real judgment calls this client cannot make honestly — so it
        # proposes none.
        redline_sources = {"instructor_rules", "authority_limit", "legal_ethical", "principal_mandate"}
        redlines = [
            AIRedlineDraft(
                statement=AIReviewedText(
                    value=c.statement.current_value, evidence_status=c.statement.evidence_status,
                    evidence=c.statement.evidence,
                ),
                source_type=c.source_type,
                consequence_if_crossed="Not established by the materials.",
                evidence=c.statement.evidence,
            )
            for c in request.constraints
            if c.source_type in redline_sources
        ]
        return ConstraintClassificationDraft(redline_candidates=redlines, bottomline_candidates=[])

    def generate_options(self, request: OptionRequest) -> list[AIOptionDraft]:
        return _fake_options(request)

    def build_haggle_plan(self, request: HaggleRequest) -> HagglePlanDraft:
        # Real MESO/anchor construction needs judgment about value
        # equivalence and market context this client doesn't have. It
        # groups the real options it was given mechanically (never invents
        # a package's content) and is upfront that equivalence is
        # unverified. It leaves the concession ladder empty rather than
        # inventing plausible-looking numbers with no real basis, and uses
        # generic (fact-free) counter-tactic lines that apply to any
        # negotiation.
        packages = []
        if request.options:
            group_count = min(3, max(1, len(request.options)))
            groups = [request.options[i::group_count] for i in range(group_count)]
            for i, group in enumerate(groups, start=1):
                if not group:
                    continue
                packages.append(
                    AIPackageDraft(
                        label=f"Package {i}",
                        option_ids=[o.id for o in group],
                        what_i_give=[o.title for o in group if o.cost_to_me in ("low", "medium")],
                        what_i_get=[o.title for o in group if o.value_to_them_hypothesis in ("low", "medium", "unknown")],
                        equivalence_note="Grouped mechanically by available options — value equivalence not verified.",
                    )
                )

        anchor = "Not established — insufficient case data for a specific anchor figure."
        justification_standard = "Not established — no verified objective criterion available in the materials."

        return HagglePlanDraft(
            packages=packages,
            anchor=anchor,
            justification_standard=justification_standard,
            concession_ladder=[],
            counter_tactics=[
                CounterTactic(tactic="extreme anchor", response_line="That's well outside what comparable terms suggest — let's ground this in objective criteria."),
                CounterTactic(tactic="artificial deadline", response_line="We want to get this right, not fast — let's take the time the decision deserves."),
                CounterTactic(tactic="final offer", response_line="Understood — let us take a moment to consider whether that works on our end."),
                CounterTactic(tactic="nibbling", response_line="Let's finalize what we've already agreed before adding anything new."),
                CounterTactic(tactic="escalation to an absent authority", response_line="Let's identify what it would take to get a decision-maker in the room."),
                CounterTactic(tactic="personal pressure", response_line="I hear you, and I want to keep this constructive — let's focus on the terms."),
            ],
        )

    def generate_brief(self, request: BriefRequest) -> BriefProseDraft:
        # Mechanical composition from already-real data — never invents a
        # fact, but also never writes natural prose the way a real model
        # would. Honest and structurally valid, not eloquent.
        case = request.case
        my_role = case.my_role.current_value if case.my_role and case.my_role.current_value else "Unknown role"
        counterpart_role = (
            case.counterpart_role.current_value if case.counterpart_role and case.counterpart_role.current_value else "Unknown counterpart"
        )
        case_summary = f"{my_role} negotiating with {counterpart_role}."

        objective_summary = (
            case.objective.current_value if case.objective and case.objective.current_value else "Not established."
        )
        success_criteria = [
            f"Reach agreement on: {issue.title}" for issue in case.issues[:3]
        ]

        analysis = case.analysis
        shared_statements = []
        questions = []
        if analysis:
            shared_statements = [a.statement for a in analysis.agreement_landscape if a.standing == "shared"]
            questions = [a.verification_question for a in analysis.agreement_landscape if a.verification_question]
        questions += [q.question for q in case.open_questions]

        opening_lines = []
        if shared_statements:
            opening_lines.append(shared_statements[0])
        if case.issues:
            opening_lines.append(f"We'd like to start by discussing {case.issues[0].title}.")
        if questions:
            opening_lines.append(questions[0])
        opening_plan = " ".join(opening_lines) or "Not established — insufficient shared context for an opening."

        return BriefProseDraft(
            case_summary=case_summary,
            objective_summary=objective_summary,
            success_criteria=success_criteria,
            opening_plan=opening_plan,
            questions_to_ask=questions[:7],
        )

    def phrase_in_english(self, request: PhraseInEnglishRequest) -> list[AIEnglishVariantDraft]:
        # Real phrasing needs actual translation/writing ability. Honest
        # fallback: say plainly that phrasing is unavailable rather than
        # pretending the original text is an English draft.
        original = request.draft_request.user_input
        return [
            AIEnglishVariantDraft(
                label="natural",
                english_draft=f"[Fake mode: automatic phrasing unavailable without an API key.]\n\n{original}",
                chinese_back_translation=original,
                risk_flags=[],
            )
        ]

    def draft_bilingual_reply(self, request: BilingualReplyRequest) -> AIBilingualReplyDraft:
        original = request.draft_request.user_input
        placeholder = "[Fake mode: automatic drafting unavailable without an API key.]"
        return AIBilingualReplyDraft(
            counterpart_summary_zh=None,
            counterpart_summary_en=None,
            points_to_verify=[],
            chinese_draft=f"{placeholder}\n\n{original}",
            english_draft=f"{placeholder}\n\n{original}",
            risk_flags=[],
        )

    def analyze_walk_away(self, request: WalkAwayRequest) -> AIWalkAwayDraft:
        # Judging BATNA quality, writing an exit script, and estimating a
        # reservation value all need real reasoning about this specific
        # case. Honest fallback: report that the BATNA is unknown rather
        # than inventing one, and use a generic (fact-free) exit line that
        # never asserts anything specific about this negotiation.
        return AIWalkAwayDraft(
            my_batna=AIReviewedText(value=None, evidence_status="unknown", evidence=[]),
            batna_quality="unknown",
            quality_rationale="Materials do not establish a clear BATNA; a rule-based reader cannot infer one honestly.",
            actions_to_improve_batna=[],
            estimated_reservation_value=None,
            reservation_derivation=None,
            counterpart_batna_hypothesis=None,
            tests_to_probe_their_batna=[],
            walk_away_triggers=[],
            exit_script="Thank you for the discussion today — we need more time before we can commit to these terms.",
            do_not_disclose=[],
        )

    def map_positions_to_interests(self, request: PositionMapRequest) -> list[AIPositionLinkDraft]:
        # Real semantic linking needs language understanding this client
        # doesn't have; the one safe, non-fabricated signal available is
        # "this position and this interest cite the same source document."
        links = []
        for position in request.positions:
            position_doc_ids = {e.document_id for e in position.statement.evidence}
            matching_ids = [
                interest.id
                for interest in request.interests
                if {e.document_id for e in interest.statement.evidence} & position_doc_ids
            ]
            links.append(
                AIPositionLinkDraft(
                    ref=position.ref,
                    underlying_interest_ids=matching_ids,
                    inference_basis="co-occurs in the same source document" if matching_ids else "no shared source document found",
                    reframe_question=None,
                    misalignment_note=None,
                )
            )
        return links
