# Negotiation Copilot — Engineering Spec (v2)

> **阅读指南（中文）**：本文件是 v1 计划的重写版，主要变化是在 pipeline 中间插入了一整层"谈判分析层"（§8）：needs/fears/motives/values、positions vs interests、islands of agreement、walk-away 分析、redlines vs bottomlines、expand the pie 的 option 生成、以及 packages + haggle plan。Brief 结构（§10）随之重写，UI 增加一个 Strategy Lab 页面（§12）。PDF 读取与材料关系判断（§5–§6）沿用 v1，只做小改。正文用英文书写，方便 Claude Code 直接消化。

Section anchors in this file are stable; `docs/TASKS.md` references them by number.

---

## 1. Product goal

A local Streamlit app. The user uploads or pastes negotiation simulation materials, and the system:

1. Reads every PDF reliably — text, numbers, dates, tables, layout-dependent content — with page-level evidence.
2. Chooses native text extraction or AI/multimodal reading per page, but presents one unified result.
3. Decides how materials relate (chronological, versioned, thematic, complementary, independent, mixed) **before** assuming any timeline exists.
4. Summarizes each document and synthesizes all of them.
5. Converts the case into machine-readable structure (`NegotiationCase`).
6. Runs the negotiation analysis layer (§8): interests, agreement landscape, walk-away, constraints, options, packages.
7. Exposes real intermediate computations in the UI (§9).
8. Produces a Living Negotiation Brief (§10) usable both in preparation and live.
9. Lets the user add judgment and timestamped notes to every Brief section.
10. Turns Chinese intent into negotiation-ready English, and drafts bilingual replies to counterpart statements the user pastes in.

Out of scope for v1: predicting outcomes, scoring utilities, deciding for the user.

## 2. Course requirement mapping

| Requirement | v1 implementation |
| --- | --- |
| Ingest textual information | PDF / DOCX / TXT / MD upload + pasted text |
| Support real Simulation 1 materials | Judged by "can it read the key information correctly", via native extraction + AI reading |
| Summarize the materials | Per-document summaries + all-materials case overview; timeline only when temporally applicable |
| Convert text to machine-friendly format via LLM | Structured Outputs → `NegotiationCase` and the §8 analysis objects |
| Output internal computations in a basic interface | Every pipeline stage shows its real input/output for the uploaded materials |
| Allow human ingestion and exploration | Document tabs, page evidence, order confirmation, field editing, issue/option filtering |
| Support practical human use | Living Brief, section notes, ZH→EN phrasing, bilingual reply drafts |
| Run locally | Streamlit on localhost |

## 3. P0 user flow

```text
open local app
→ upload / paste materials, pick a scope per material
→ native parse; detect pages needing AI reading
→ AI reads PDFs (text, numbers, tables, clauses) with page evidence
→ classify material relationships; propose order only if evidence supports it
→ per-document summary + structured extraction
→ consolidate issues / constraints / conflicts / unknowns
→ ANALYSIS LAYER:
    needs·fears·motives·values (both parties)
    positions vs interests map
    islands of agreement (shared vs contested facts and values)
    walk-away analysis (BATNA → reservation value → triggers → exit script)
    redlines (confirmed) vs bottomlines (flexible thresholds)
    expand the pie → option inventory
    packages (MESOs) + concession ladder + counter-tactics
→ user reviews evidence, confirms redlines/bottomlines, accepts/rejects options
→ generate Prep Brief + Live Card
→ live: annotate sections, add timestamped notes
→ ZH idea → EN phrasing; counterpart statement → bilingual reply draft
→ export Brief markdown + case JSON
```

Three gates hold throughout:

1. PDF reading results and sources are visible and checkable.
2. Chronology must be justified before it is displayed.
3. Nothing unconfirmed by the user is displayed as a hard limit — this now covers **both** redlines and bottomlines.

## 4. Inputs and material management

### 4.1 Accepted inputs
PDF (text-based, image-based, complex layout), DOCX, TXT, Markdown, pasted text.

Per material record: `document_id`, original filename, upload index, file type and size, SHA-256, page/paragraph count, parse method, per-page reading method, pages needing review, user-selected scope, processing status, warnings.

### 4.2 Scopes
`MY_CONFIDENTIAL` · `SHARED` · `INSTRUCTOR_RULES`. No counterpart-confidential scope in v1.

### 4.3 Safety and failure recovery
Validate extension, MIME, per-file and total size. Safe filenames, session-local UUIDs. Reject executables and path traversal. Reuse parse results for identical hashes. A failed page or document must not discard successful ones. Raw material, reading results, and structured results are stored separately so the pipeline stays inspectable.

## 5. PDF reading and understanding

### 5.1 Acceptance goal
OCR is not a user-facing feature. The requirement: whatever is inside the PDF — selectable text, page images, tables, complex layout — the system reads the negotiation-relevant information correctly and cites checkable page numbers.

Must reliably capture: roles, organizations, person names; amounts, percentages, quantities, units; dates, deadlines, event sequence; clauses, authority limits, prohibitions; core rows/columns of tables; cross-references to other documents.

### 5.2 Adaptive reading strategy
1. Extract native per-page text with 1-based page numbers.
2. Assess sufficiency (empty pages, garbled text, missing tables, very low text density).
3. Sufficient pages → pass paginated text straight to extraction.
4. Insufficient or visually structured pages → use the OpenAI PDF/file input or multimodal page input.
5. Normalize every route into `PDFPageResult`; downstream stages are route-agnostic.
6. Unreadable regions → `needs_review`. Never reconstruct from context.

Prefer the officially supported direct PDF input; render pages inside the adapter only if the SDK/model requires it. Business logic must not bind to one route.

### 5.3 Reading rules
Model from `OPENAI_MODEL`. Keep page numbers and short supporting excerpts. Double-check numbers, currencies, dates, negations. Tables need row/column correspondence, not visual fidelity. No full verbatim transcript required. Use `quality_flags` and `needs_review` for blurred/truncated regions. Allow re-analysis of a whole PDF or of failed pages. Preserve partial results on API error/rate limit. Enforce `MAX_UPLOAD_MB` and `MAX_PDF_PAGES`, and show the processing scope before calling.

### 5.4 Unified structure

```python
class PDFPageResult(BaseModel):
    document_id: str
    page_number: int
    reading_method: Literal["native_text", "ai_pdf", "ai_vision"]
    content: str
    key_items: list[str]
    quality_flags: list[str]
    status: Literal["success", "needs_review", "failed"]
    error_type: str | None = None
```

### 5.5 Testing
`FakeAIClient` returns deterministic page-level results for checked-in PDF fixtures. Fixtures are ordinary test data; tests never depend on a chat session. Tests assert key roles, amounts, dates, clauses, table relations, and page numbers — not verbatim equality. With a key configured, `RUN_LIVE_OPENAI_TESTS=true` runs live tests over one text PDF and one PDF that plain extraction cannot fully understand. Live tests never replace offline tests.

## 6. Material relationships and conditional chronology

### 6.1 Relationship modes
`chronological` · `versioned` · `thematic` · `complementary` · `independent` · `mixed`.

Whatever the mode, **all permitted materials are read and synthesized**. Organization affects presentation only, never inclusion.

### 6.2 Two-phase judgment
**Phase A — per-document cues:** dates/deadlines/relative time; `draft|revised|final` markers; cross-references to other documents, meetings, offers; document type and purpose; main topics; role and authority scope; page/paragraph plus excerpt.

**Phase B — cross-document organization:** proposed `organization_mode`; whether chronological order is genuinely needed; if yes, proposed order with before/after evidence; if no, thematic or document-type groups; pairwise relations; `high|medium|low` confidence; unresolved ambiguities; a short user-facing rationale (no hidden reasoning stored).

Evidence priority when ordering: explicit in-text dates and references > version markers > metadata > filename > upload order. Filenames never override body text.

### 6.3 User confirmation and UI
Show the relationship mode first, not a timeline. Chronological/versioned → compare Upload order, Filename order, AI proposed order. Thematic/complementary → show groups and the issues each covers. Independent → provide an index, invent no order. Mixed → order only the temporal subset. The user may accept, edit, or disable the proposal. Low confidence and conflicting evidence must be visible.

### 6.4 Structures

```python
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
    groups: list[DocumentGroup]
    relations: list[DocumentRelation]
    unresolved_ambiguities: list[str]
    review_status: Literal["unreviewed", "confirmed", "edited_by_user"]
```

## 7. Summaries, extraction, consolidation

### 7.1 Per-document summary
3–6 bullets; the document's role and purpose; explicit numbers, dates, deadlines; the 1–3 items that matter most for the negotiation; its relationship to other materials; parsing/reading/extraction warnings. Every bullet links back to its page or paragraph.

### 7.2 Machine-readable extraction
Extract at minimum: my role and counterpart role; context; objective; interests; positions; BATNA; issues; targets; reservation point or other hard constraints; authority limits; deadlines; possible concessions and tradeoffs; counterpart information; open questions; evidence; conflicts and warnings.

Every conclusion is tagged `explicit | inferred | unknown | user_confirmed`. Numbers absent from the materials return `null`.

### 7.3 Cross-document consolidation
Use the confirmed organization to build a case overview across all permitted documents. Merge semantically identical issues while keeping all evidence. Create a `Conflict` for inconsistent numbers, dates, authority scopes, or rules. Never let a newer document silently supersede an older one unless the text says so, and show the basis in the UI. Unresolvable items become `OpenQuestion`. Keep both per-document and consolidated results for pipeline display.

---

## 8. Negotiation analysis layer (NEW — the core of v2)

This layer runs after consolidation and before Brief generation. Each stage is a separate AI call with Structured Outputs, a separate service module, a separate fake fixture, and its own visible intermediate output. **Stages run in this order because each consumes the previous one.**

```text
8.1 Interests        needs / fears / motives / values, per party
8.2 Positions map    stated position → underlying interests
8.3 Islands          shared vs contested facts and values
8.4 Walk-away        BATNA → reservation value → triggers → exit script
8.5 Constraints      redlines (immovable) vs bottomlines (flexible, BATNA-derived)
8.6 Options          expand the pie, invention only, no evaluation
8.7 Packages         MESOs + concession ladder + counter-tactics (haggle prep)
```

### 8.1 Interests: needs, fears, motives, values

For **me** and for the **counterpart**, produce four separate lists. Do not blend them.

| Field | Question it answers | Notes |
| --- | --- | --- |
| `needs` | What must be satisfied for this party to say yes? | Substantive and procedural (e.g. cash flow, cover, a defensible record) |
| `fears` | What loss or risk is this party trying to avoid? | Loss framing often explains rigid positions |
| `motives` | What drives them beyond this deal? | Incentives, constituencies, precedent, reputation, career, time pressure |
| `values` | What principles or fairness norms do they invoke? | Equity, equality, need, precedent, legality, reciprocity, identity |

Rules:
- Every item carries evidence + `evidence_status`. Items with no textual basis are `inferred` and must include `verification_question`.
- **All counterpart items are hypotheses** regardless of status, and render with `Hypothesis — verify in conversation`.
- Counterpart items may only be derived from `shared` and `instructor_rules` materials plus explicit user input; never claim knowledge of their confidential brief.
- If materials are thin, return few high-quality items plus open questions. Do not pad with generic negotiation clichés.

### 8.2 Positions vs interests

For each stated position (mine or theirs), link the underlying interests and state the inference basis.

- A position is a *statement about the solution*; an interest is a *statement about why*.
- Mark each link `explicit` (the text says why) or `inferred` (we reasoned it) with a one-line basis.
- For each position, add `reframe_question`: a question that moves the conversation from the position to the interest ("What would the earlier delivery date let you do?").
- Flag positions where my own stated position may not actually serve my interests — this is a preparation insight, not a recommendation.

### 8.3 Islands of agreement

Classify every material claim into a shared/contested landscape. This is the platform to build on and the map of what must be verified.

| `kind` | `standing` values | Use in Brief |
| --- | --- | --- |
| `fact` | `shared` (both sides' materials agree) / `contested` (materials disagree) / `unverified` (only one side's material asserts it) | Shared facts anchor the opening; contested facts become verification questions |
| `value` | same | Shared values supply the objective criteria for the haggle plan; contested values predict the fairness fight |
| `process` | same | Agenda, sequence, authority, deadline handling |

Rules:
- An item is `shared` only with evidence from materials both parties can see, or from an explicit statement that both accept it. One-sided assertions are `unverified`, never `shared`.
- Every `contested` and `unverified` item generates a `verification_question` that feeds the Brief's Questions section.
- Contested numeric facts must reuse the existing `Conflict` records from §7.3 rather than duplicating them — link by `conflict_id`.
- Do not resolve contested facts by picking the more recent or more confident source.

### 8.4 Walk-away analysis

Runs **before** constraint classification, because bottomlines are derived from it.

Produce:
- `my_batna` — the most realistic alternative if no deal, described concretely, with evidence.
- `batna_quality` — `strong | moderate | weak | unknown`, with the reason.
- `actions_to_improve_batna` — what could be done before or during the negotiation to strengthen it.
- `estimated_reservation_value` — the point of indifference between this deal and the BATNA, kept as text with units, plus how it was derived. If BATNA is `unknown`, this is `null` and the case is flagged with a preparation gap.
- `counterpart_batna_hypothesis` + `tests_to_probe` — questions or signals that would reveal how good their alternative is.
- `walk_away_triggers` — explicit, checkable conditions that mean stop or pause ("they refuse any delivery commitment in writing").
- `exit_script` — 2–3 sentences that decline without burning the relationship and leave the door open.
- `do_not_disclose` — the list of items the language assistant must never surface.

Rules: walk-away is always modeled, always visible to the user, never disclosed in a draft. Aspiration must never be used as a reservation value.

### 8.5 Redlines vs bottomlines

Two different objects. Do not merge them.

**Redline** — immovable. Sources allowed: `instructor_rules`, `authority_limit`, `legal_ethical`, `principal_mandate`. Binary: crossing it means no deal, regardless of compensation elsewhere. AI may only propose *candidates*; `confirmed_by_user=True` is required before it enters the Brief's Redlines section or the package validator.

**Bottomline** — flexible threshold on an issue where risk starts to outweigh benefit. Fields: `issue_id`, `threshold_value` (text with units), `direction` (`min|max`), `rationale`, `linked_batna_reference`, `risk_if_crossed`, `revisit_conditions` (what new information would move it), `confirmed_by_user`.

Rules:
- A bottomline without a link to the walk-away analysis is `provisional` and surfaces as a preparation gap.
- Never auto-promote a target into a bottomline, or a bottomline into a redline.
- The user can demote a redline candidate to a bottomline and vice versa; both actions are logged with `ai_original_value` preserved.
- Show redlines and bottomlines in the same UI panel but visually distinct, with an explicit "immovable vs flexible" label.

### 8.6 Option generation — expand the pie

Divergent stage. **Invention is separated from decision:** this stage may not evaluate feasibility, may not reject, may not rank.

Generation heuristics the prompt must apply explicitly:
- differences in **valuation** (they value what is cheap for me),
- differences in **time preference** (staged, deferred, accelerated),
- differences in **risk preference** (contingent agreements, performance-based terms, escrow),
- differences in **capability** (each side contributes what it does cheaply),
- **unbundling** an issue into components,
- **adding issues** to trade across,
- **non-monetary** value: recognition, information, precedent, exclusivity, referrals, process,
- **process options**: pilots, review points, renegotiation clauses, sunset dates.

Each option:
```
id, title, description (1–2 sentences), option_type,
serves_my_interests: [interest ids], serves_their_interests_hypothesis: [interest ids],
cost_to_me: low|medium|high|unknown, value_to_them_hypothesis: low|medium|high|unknown,
depends_on: [assumptions to verify], evidence_status, status: idea|viable|rejected (user-set only)
```

Rules: aim for breadth (target ≥ 8 options for a normal case, spanning ≥ 4 option types). Never present an option as an offer. Only the user, or the redline validator, may set `rejected`. Every option must name at least one interest from §8.1 — options that serve nobody's interest are a prompt failure.

### 8.7 Packages and haggle prep

Convergent stage. Distributive preparation, done consciously and after the integrative work.

Produce:
1. **Trade currency table** — what is cheap for me and valuable for them, and the reverse. Derived from option costs and interest matches.
2. **MESOs** — 2–3 packages of roughly equal value to me, materially different in composition, so their choice reveals their priorities. Each: `label`, `option_ids`, `what_i_give`, `what_i_get`, `equivalence_note`, `redline_check` (must pass the validator).
3. **Anchor plan** — the opening ask, and the **objective criterion** that justifies it (market rate, precedent, cost basis, a shared value from §8.3). An anchor without a justification standard is invalid.
4. **Concession ladder** — ordered steps, each with `issue_id`, `from_value`, `to_value`, `ask_in_return` (never unconditional), and `trigger_condition`. Increments must shrink as the ladder descends; the last step must sit above the bottomline, and the ladder must never reach a redline.
5. **Counter-tactic playbook** — short responses to: extreme anchor, artificial deadline, "final offer", nibbling, escalation to an absent authority, personal pressure. Each entry is one sentence the user can actually say.
6. **Walk-away reminder** — every package view repeats the reservation value and triggers from §8.4, marked private.

Validator (plain code, not AI): for each package and each concession step, check against confirmed redlines and bottomlines; emit `violates_redline` / `crosses_bottomline` / `unconditional_concession` warnings. This validator is a testable pure function.

---

## 9. Data models (additions to §8 of v1)

Existing models `Evidence`, `ReviewedText`, `DocumentRecord`, `NegotiationIssue`, `Constraint`, `Deadline`, `Conflict`, `OpenQuestion`, `NegotiationCase` are retained. `NegotiationCase` gains an `analysis: NegotiationAnalysis` field.

```python
class InterestItem(BaseModel):
    id: str
    party: Literal["me", "counterpart"]
    category: Literal["need", "fear", "motive", "value"]
    statement: ReviewedText
    verification_question: str | None = None
    is_hypothesis: bool = False          # always True for counterpart


class PositionInterestLink(BaseModel):
    id: str
    party: Literal["me", "counterpart"]
    stated_position: ReviewedText
    underlying_interest_ids: list[str]
    inference_basis: str
    reframe_question: str | None = None
    misalignment_note: str | None = None


class AgreementItem(BaseModel):
    id: str
    kind: Literal["fact", "value", "process"]
    statement: str
    standing: Literal["shared", "contested", "unverified"]
    my_view: str | None = None
    counterpart_view: str | None = None
    conflict_id: str | None = None
    verification_question: str | None = None
    evidence: list[Evidence]


class WalkAwayAnalysis(BaseModel):
    my_batna: ReviewedText
    batna_quality: Literal["strong", "moderate", "weak", "unknown"]
    quality_rationale: str
    actions_to_improve_batna: list[str]
    estimated_reservation_value: ReviewedText | None
    reservation_derivation: str | None
    counterpart_batna_hypothesis: ReviewedText | None
    tests_to_probe_their_batna: list[str]
    walk_away_triggers: list[str]
    exit_script: str
    do_not_disclose: list[str]


class Redline(BaseModel):
    id: str
    statement: ReviewedText
    source_type: Literal["instructor_rules", "authority_limit", "legal_ethical", "principal_mandate"]
    consequence_if_crossed: str
    confirmed_by_user: bool = False
    evidence: list[Evidence]


class Bottomline(BaseModel):
    id: str
    issue_id: str | None
    threshold_value: ReviewedText          # keep units as text; do not force float
    direction: Literal["min", "max"]
    rationale: str
    linked_batna_reference: str | None
    risk_if_crossed: str
    revisit_conditions: list[str]
    provisional: bool = True               # False only when BATNA-linked and confirmed
    confirmed_by_user: bool = False
    evidence: list[Evidence]


class NegotiationOption(BaseModel):
    id: str
    title: str
    description: str
    option_type: Literal["valuation", "time", "risk", "capability",
                         "unbundle", "add_issue", "non_monetary", "process"]
    serves_my_interest_ids: list[str]
    serves_their_interest_ids: list[str]
    cost_to_me: Literal["low", "medium", "high", "unknown"]
    value_to_them_hypothesis: Literal["low", "medium", "high", "unknown"]
    depends_on: list[str]
    evidence_status: Literal["explicit", "inferred", "unknown", "user_confirmed"]
    status: Literal["idea", "viable", "rejected"] = "idea"


class TradeCurrency(BaseModel):
    item: str
    cost_to_me: Literal["low", "medium", "high", "unknown"]
    value_to_them_hypothesis: Literal["low", "medium", "high", "unknown"]
    direction: Literal["i_can_give", "i_want_to_get"]


class TradePackage(BaseModel):
    id: str
    label: str
    option_ids: list[str]
    what_i_give: list[str]
    what_i_get: list[str]
    equivalence_note: str
    validator_warnings: list[str] = []


class ConcessionStep(BaseModel):
    order: int
    issue_id: str | None
    from_value: str
    to_value: str
    ask_in_return: str                     # never empty
    trigger_condition: str


class CounterTactic(BaseModel):
    tactic: str
    response_line: str


class HagglePlan(BaseModel):
    anchor: str
    justification_standard: str            # objective criterion; required
    trade_currencies: list[TradeCurrency]
    packages: list[TradePackage]
    concession_ladder: list[ConcessionStep]
    counter_tactics: list[CounterTactic]
    validator_warnings: list[str] = []


class NegotiationAnalysis(BaseModel):
    interests: list[InterestItem]
    position_links: list[PositionInterestLink]
    agreement_landscape: list[AgreementItem]
    walk_away: WalkAwayAnalysis
    redlines: list[Redline]
    bottomlines: list[Bottomline]
    options: list[NegotiationOption]
    haggle_plan: HagglePlan
    generation_notes: list[str]
```

User edits always preserve `ai_original_value`. If normalization is unreliable, `current_value` keeps the original text with units.

## 10. The Living Brief

### 10.1 Two views, one data source

- **Prep Brief** — full structure below, for preparation. May span more than a page.
- **Live Card** — a compressed view for use during the negotiation: Walk-away line, Redlines, my top 3 interests, their top 3 hypothesized interests, shared-facts opener, the 3 packages, next 3 questions, plus any pinned sections. Fits on one screen with no long scrolling.

Both are generated from the same `NegotiationCase` + `NegotiationAnalysis`. Every field shows a compact source tag such as `[Role Brief, p. 3]` that expands to full evidence.

### 10.2 Prep Brief sections

| # | Section | Content | Generation rules |
| --- | --- | --- | --- |
| 1 | **Case Snapshot** | Simulation, my role, counterpart role, stage | Unknown roles say `Unknown`; no guessing |
| 2 | **Objective & Success Criteria** | The outcome in 1–2 sentences + 2–3 checkable criteria | Aspiration is never written as a hard target |
| 3 | **Walk-Away Position** | BATNA, quality, reservation value, triggers, exit script, BATNA-improving actions | Private-marked. `Not established` when absent, and listed as a preparation gap |
| 4 | **My Needs / Fears / Motives / Values** | Four short lists | Separate explicit from inferred |
| 5 | **Their Needs / Fears / Motives / Values** | Four short lists | Every item tagged `Hypothesis — verify`; each carries a probe question |
| 6 | **Positions vs Interests** | Their position → likely interest; my position → my interest; reframe questions | Positions quoted, interests labeled with inference basis |
| 7 | **Islands of Agreement** | Shared facts, shared values, shared process points | Only material-supported shared items; this is the opening platform |
| 8 | **Contested Ground** | Contested facts, contested values, unverified assertions | Each with its verification question; contested numbers link to `Conflict` |
| 9 | **Redlines (immovable)** | Confirmed redlines + consequence | Only `confirmed_by_user=True` |
| 10 | **Bottomlines (flexible)** | Threshold, direction, rationale, revisit conditions | Provisional ones marked; unconfirmed ones go to §17 instead |
| 11 | **Issue Map** | Per issue: target, acceptable range, priority, flexibility, status | Max 5 shown, rest collapsed; units preserved |
| 12 | **Expand the Pie — Options** | Option inventory grouped by option type | Options are possibilities, never offers; assumptions shown |
| 13 | **Packages (MESOs)** | 2–3 equivalent-value packages with give/get | Must pass the redline/bottomline validator |
| 14 | **Haggle Plan** | Anchor + justification standard, concession ladder, counter-tactics | Every concession has an `ask_in_return`; ladder stops above the bottomline |
| 15 | **Questions to Ask** | 5–7 questions | Sourced from verification questions, interest probes, BATNA probes, open questions |
| 16 | **Opening Plan** | ~60–100 word opening, first issue, first question | Opens from islands of agreement; never reveals BATNA, reservation value, or bottomline |
| 17 | **Uncertainties, Conflicts & Gaps** | Unconfirmed constraints, numeric conflicts, ordering ambiguity, missing info | Never hidden for layout reasons |
| 18 | **Key Events / Deadlines** | Timeline only if `temporal_order_applicable`, otherwise a thematic list | Absence of a timeline is not a defect |

### 10.3 Priority when space is tight

1. Redlines and walk-away triggers → 2. Bottomlines → 3. Objective and BATNA → 4. Top interests both sides → 5. Islands of agreement → 6. Packages → 7. Questions → 8. Options and hypotheses.

Default caps: 4 items per NFMV list, 5 issues, 3 packages, 7 questions, 8 options visible (rest collapsed by type), opening ~60–100 words. Bullets and short sentences only.

### 10.4 Human judgment and notes layer

Every section carries the same interaction structure: **AI base** (with evidence) · **My Judgment** · **Live Notes** (timestamped) · **Status** (`confirmed|tentative|needs_verification|no_longer_relevant`) · **Pin** · **Evidence** (collapsed).

Rules: judgment and notes are stored separately from AI content and autosaved locally with timestamps; the user can edit and delete them; a live note never becomes a confirmed fact, constraint, or agreement by itself; promoting a note to the case requires an explicit "Promote to case" click with a target field type; regenerating the Brief preserves all human content; exports include My Judgment by default and live notes optionally.

### 10.5 Brief safety rules

- `inferred` and `unknown` keep visible labels.
- Unconfirmed redline candidates never appear as redlines; unconfirmed bottomlines never appear as thresholds.
- Counterpart interests never render as facts.
- Options and packages never render as agreed or offered.
- No chronology from filenames; timeline warnings only when chronology applies and order is unconfirmed.
- Unreliable PDF regions affecting key numbers → `Verify source page`.
- Editing the case or the organization marks affected AI bases stale; human content survives.
- Generation notes list which confirmed fields were used and which unconfirmed fields were excluded.

## 11. Live workspace and language assistant

The assistant only processes what the user types or pastes. No microphone, no meeting capture, no sending.

### 11.1 Mode A — Chinese intent → negotiation English
User writes their rough Chinese intent, optionally choosing intent (ask, decline, clarify, propose conditional, trade concession, summarize agreement), tone (`collaborative|neutral|firm`), length, protected terms (numbers, names, conditions), and referenced Brief sections.

Output ≤ 3 variants: **Natural/Neutral**, **Collaborative**, **Firm**. Each shows the English draft, a short Chinese back-translation, a tone label, and warnings if a new number, new commitment, or possible concession appeared. This is not literal translation; it preserves substance while producing speakable negotiation English.

### 11.2 Mode B — Counterpart statement → bilingual reply draft
User pastes the counterpart's Chinese or English statement. Language auto-detected. User may add: next objective, tone, referenced Brief sections, whether to ask before answering, and information that must not be disclosed.

Output: **What I heard** (1–2 sentences) · **Points to verify** · **Chinese draft** · **English draft** · **Risk flags**. One pair by default; one targeted rewrite via "more collaborative / concise / firm".

### 11.3 Context and safety rules
Default context: current user input, confirmed Brief content, user-selected judgment and notes. Never uses counterpart confidential information. Never introduces new amounts, dates, commitments, threats, or concessions. Numbers, units, negations, and conditionals must match the user's input. If the draft conflicts with a confirmed constraint, warn first and let the user decide. Output stays short. Drafts are editable, copyable, savable as notes, never auto-sent. Live history is local and clearable.

Risk flag set (extended for v2):
`reveals_batna` · `reveals_reservation_value` · `reveals_bottomline` · `crosses_redline` · `unconditional_concession` · `new_commitment` · `asserts_contested_fact_as_agreed` · `contradicts_confirmed_field`

The last one matters: a draft must not state a `contested` or `unverified` item from §8.3 as if it were shared.

### 11.4 Language models

```python
class BriefNote(BaseModel):
    id: str
    section_id: str
    note_type: Literal["my_judgment", "live_note"]
    text: str
    created_at: datetime
    updated_at: datetime


class BriefSectionState(BaseModel):
    section_id: str
    title: str
    ai_generated_base: str
    evidence: list[Evidence]
    status: Literal["confirmed", "tentative", "needs_verification", "no_longer_relevant"]
    pinned: bool = False
    stale: bool = False
    notes: list[BriefNote]


class LanguageDraftRequest(BaseModel):
    mode: Literal["chinese_to_english", "reply_to_counterpart"]
    user_input: str
    input_language: Literal["zh", "en", "mixed", "auto"]
    intent: str | None
    tone: Literal["collaborative", "neutral", "firm"]
    selected_brief_section_ids: list[str]
    protected_terms: list[str]
    do_not_disclose: list[str]


class EnglishPhraseVariant(BaseModel):
    label: Literal["natural", "collaborative", "firm"]
    english_draft: str
    chinese_back_translation: str
    risk_flags: list[str]


class BilingualReplyDraft(BaseModel):
    counterpart_summary_zh: str | None
    counterpart_summary_en: str | None
    points_to_verify: list[str]
    chinese_draft: str
    english_draft: str
    risk_flags: list[str]


class LiveInteraction(BaseModel):
    id: str
    created_at: datetime
    mode: Literal["chinese_to_english", "reply_to_counterpart"]
    user_input: str
    selected_brief_section_ids: list[str]
    output: dict
    saved_note_id: str | None = None


class LiveWorkspaceState(BaseModel):
    brief_sections: list[BriefSectionState]
    interaction_history: list[LiveInteraction]
```

## 12. Information architecture

One Streamlit app, six pages.

**Page 1 — Materials.** Upload/paste, scope selection, page counts, native vs AI-assisted counts, status, "Process Materials", per-page retry, local-data and confidentiality reminder.

**Page 2 — Pipeline & Relationships.** Per-page reading status and method, expandable reading results with key items and quality flags, per-document summaries, relationship cues, proposed mode, order comparison (upload/filename/AI) or thematic groups, rationale/confidence/ambiguity, Accept/Edit, structured JSON expander per stage.

**Page 3 — Negotiation Map.** Roles, context, objective, BATNA, interests, positions, issue table by importance, constraints, deadlines, conflicts, open questions, status labels, evidence viewer, Confirm/Edit/Reject.

**Page 4 — Strategy Lab (NEW).** Five tabs mirroring §8:
- *Interests* — NFMV grids for both parties; positions↔interests map with reframe questions.
- *Agreement Landscape* — shared / contested / unverified board, each contested item showing its verification question.
- *Walk-Away* — BATNA, quality, reservation value derivation, triggers, exit script, probes for their BATNA. Marked private.
- *Limits* — redline candidates and bottomline candidates side by side, with confirm / demote / promote / reject controls and the immovable-vs-flexible distinction made explicit.
- *Options & Packages* — option inventory filterable by type and by interest served, "Generate more options" button, package builder with live validator warnings, concession ladder editor, counter-tactic list.

**Page 5 — Brief Builder & Export.** Prep Brief preview, Live Card preview, readiness warnings, generation notes, per-section judgment/status/pin/notes, downloads: `negotiation_brief.md`, `negotiation_case.json`, optional `pipeline_trace.json` (no keys, no unnecessary full text).

**Page 6 — Live Negotiation Workspace.** Two columns. Left: Live Card / Living Brief, pinned-only toggle, timestamped note entry, "Promote to case", filter by issue/status. Right: Language Assistant Tab A (ZH→EN) and Tab B (counterpart → bilingual reply), tone/intent/section controls, risk flags, edit/copy/save-as-note, collapsed recent history. A sticky header shows the current negotiation, confirmed red-line warnings, walk-away trigger reminder, and save status. All AI calls are button-triggered.

## 13. Architecture

### 13.1 AI client boundary

```python
class AIClient(Protocol):
    def read_pdf(self, request: PDFReadRequest) -> PDFReadResult: ...
    def extract_document(self, request: ExtractionRequest) -> DocumentExtraction: ...
    def organize_materials(self, request: MaterialOrganizationRequest) -> MaterialOrganizationResult: ...
    def consolidate_case(self, request: ConsolidationRequest) -> NegotiationCase: ...
    # analysis layer
    def analyze_interests(self, request: InterestRequest) -> InterestAnalysisResult: ...
    def map_positions_to_interests(self, request: PositionMapRequest) -> list[PositionInterestLink]: ...
    def map_agreement_landscape(self, request: AgreementRequest) -> list[AgreementItem]: ...
    def analyze_walk_away(self, request: WalkAwayRequest) -> WalkAwayAnalysis: ...
    def classify_constraints(self, request: ConstraintRequest) -> ConstraintClassificationResult: ...
    def generate_options(self, request: OptionRequest) -> list[NegotiationOption]: ...
    def build_haggle_plan(self, request: HaggleRequest) -> HagglePlan: ...
    # output
    def generate_brief(self, request: BriefRequest) -> NegotiationBrief: ...
    def phrase_in_english(self, request: LanguageDraftRequest) -> list[EnglishPhraseVariant]: ...
    def draft_bilingual_reply(self, request: LanguageDraftRequest) -> BilingualReplyDraft: ...
```

`OpenAIClient` implements these against the Responses API with Structured Outputs. `FakeAIClient` returns deterministic fixtures for all of them. Services depend on the protocol only; Streamlit pages never assemble prompts.

### 13.2 Prompts

```
prompts/
  read_pdf.md
  extract_relationship_cues.md
  organize_materials.md
  summarize_and_extract.md
  consolidate.md
  analyze_interests.md
  map_positions_to_interests.md
  map_agreement_landscape.md
  analyze_walk_away.md
  classify_constraints.md
  generate_options.md
  build_haggle_plan.md
  generate_brief.md
  phrase_in_english.md
  draft_bilingual_reply.md
```

### 13.3 Runtime environment — conda `negotiation_tool`

The project is developed and demoed inside a dedicated conda environment named **`negotiation_tool`**. This isolates the OpenAI SDK, Streamlit, and the PDF libraries from any other coursework environment, and makes the demo reproducible on another machine from two files.

Repository files:

- `environment.yml` — declares `name: negotiation_tool`, channel `conda-forge`, `python=3.11`, `pip`, and a `pip: [-r requirements.txt]` entry.
- `requirements.txt` — the application libraries (streamlit, openai, pydantic, pypdf, pymupdf, python-docx, python-dotenv, pytest).

Each dependency lives in exactly one of the two files. Anything that only needs pip stays in `requirements.txt` so the project still installs in a plain venv if conda is unavailable.

Lifecycle:

```bash
conda env create -f environment.yml     # create
conda activate negotiation_tool         # every session, before any command
conda env update -f environment.yml --prune   # after dependency changes
conda env export --from-history > environment.lock.yml   # optional, for submission
conda env remove -n negotiation_tool    # teardown
```

The README must document this as the primary install path, note the Python version, and state that `streamlit run app.py` and `pytest` are always run with the environment active. `.gitignore` excludes `.env`, `envs/`, `conda-meta/`, and `__pycache__/`.

A startup guard in `config.py` logs the interpreter path and a warning when `sys.prefix` does not end in `negotiation_tool`, so a wrong-environment run is visible immediately instead of surfacing later as a missing-module error. The warning never blocks startup — it is a diagnostic, not a gate.

### 13.4 Environment variables

```dotenv
OPENAI_API_KEY=
OPENAI_MODEL=
OPENAI_STORE_RESPONSES=false
RUN_LIVE_OPENAI_TESTS=false
APP_DATA_DIR=./data
MAX_UPLOAD_MB=25
MAX_PDF_PAGES=50
LOG_LEVEL=INFO
```

No hardcoded model names. `store=False` when `OPENAI_STORE_RESPONSES=false`. The app starts in fake/demo mode without a key. Logs never contain keys, images, full documents, or full prompts.

## 14. Testing and acceptance

### 14.1 Automated tests

Carried over from v1:
1. Native PDF pages keep correct page numbers.
2. Text-sufficient PDFs take the native path.
3. When plain extraction misses key content, the fake AI reader returns it with correct page numbers.
4. A failed or review-needed page does not discard other pages.
5. Genuinely temporal materials with misleading filenames are ordered by body text.
6. Non-temporal materials are classified thematic/complementary/independent, not forced into order.
7. Mixed mode orders only the temporal subset.
8. Low-confidence organization requires user confirmation.
9. Merged issues keep all evidence.
10. Divergent numbers create conflicts instead of silent overwrites.
11. User edits preserve `ai_original_value`.
12. Exports contain no API key and no unnecessary full text.

New for v2:
13. NFMV output separates the four categories and never puts a counterpart item in with `is_hypothesis=False`.
14. Counterpart interests are derived only from `shared` / `instructor_rules` scopes.
15. Every `contested` and `unverified` agreement item carries a verification question.
16. A one-sided assertion is never classified `shared`.
17. Contested numeric items reference an existing `conflict_id` rather than duplicating the conflict.
18. `estimated_reservation_value` is `null` and a gap is raised when `batna_quality == "unknown"`.
19. A bottomline without a BATNA link stays `provisional=True`.
20. An unconfirmed redline candidate never appears in the Brief's Redlines section.
21. Demoting a redline to a bottomline preserves `ai_original_value` and updates neither confirmation flag silently.
22. Option generation returns ≥ 8 options spanning ≥ 4 option types on the standard fixture, and never sets `status="rejected"` itself.
23. Every generated option references at least one existing interest id.
24. The package validator flags `violates_redline` for a package containing a redline-crossing option.
25. Every concession step has a non-empty `ask_in_return`; the ladder never descends past a confirmed bottomline; increments are non-increasing.
26. An anchor without `justification_standard` fails validation.
27. The Live Card contains walk-away, redlines, top interests, islands, packages, and questions within the size cap.
28. Brief regeneration preserves My Judgment, notes, status, and pins; changed inputs mark AI bases stale.
29. ZH→EN preserves numbers, conditions, negations, and core intent.
30. Counterpart input in either language yields semantically consistent ZH and EN drafts.
31. Drafts that reveal BATNA/reservation/bottomline, cross a redline, concede unconditionally, or assert a contested fact as agreed produce the corresponding risk flags.
32. Nothing auto-sends; a plain note never becomes a confirmed fact.

### 14.2 Fake end-to-end fixtures

Prepare: a native-text PDF or TXT; a short PDF whose tables/visual content plain extraction would miss; a complementary set (shared case + private brief + instructor rules) with no chronology; a temporal set whose filename numbering contradicts the body; one numeric conflict and one explicit constraint; one shared value and one contested value; one counterpart hypothesis with no evidence; a Chinese intent containing an amount and a condition; one English and one Chinese counterpart statement.

Run: upload → PDF ingestion and routing → fake AI reading → relationship cues → organization → per-document extraction → consolidation → interests → positions map → agreement landscape → walk-away → constraints → options → packages → user review fixture → Prep Brief + Live Card → section judgment and note → ZH→EN → bilingual reply → export.

### 14.3 Live API smoke test

With a key set: configure a PDF-capable, Structured-Outputs-capable model; upload representative Simulation 1 materials; verify dates, amounts, role names, key clauses, and at least two source pages; confirm no forced chronology; generate the analysis layer and check that (a) counterpart interests are hypothesis-tagged, (b) at least one contested item has a verification question, (c) the reservation value derivation is stated, (d) options span multiple types, (e) no package violates a confirmed redline; generate the Brief; add judgment and notes to two sections; run one ZH→EN and one bilingual reply; refresh and confirm notes persist; record model config, success, and known issues without storing full material text or keys.

### 14.4 Acceptance checklist

- [ ] `conda env create -f environment.yml` produces a working `negotiation_tool` environment from a clean machine
- [ ] `python -m streamlit run app.py` starts inside the activated `negotiation_tool` environment
- [ ] PDF / DOCX / TXT / Markdown / pasted text supported
- [ ] AI reads roles, dates, amounts, clauses, and key tables correctly from the test PDFs
- [ ] Per-page reading result visible with native vs AI-assisted labels
- [ ] Material relationship is judged before any timeline is shown
- [ ] Non-temporal materials organized thematically while still synthesized in full
- [ ] Temporal materials show body-text evidence and allow order confirmation
- [ ] Per-document summaries plus a whole-case overview
- [ ] Structured LLM intermediates visible per stage
- [ ] Consolidated issues, conflicts, unknowns visible
- [ ] Every key conclusion links back to a page or paragraph
- [ ] Needs / fears / motives / values produced for both parties, counterpart tagged as hypothesis
- [ ] Positions mapped to interests with reframe questions
- [ ] Islands of agreement separated from contested and unverified ground
- [ ] Walk-away analysis with BATNA, reservation value derivation, triggers, and exit script
- [ ] Redlines and bottomlines clearly distinguished and separately confirmed
- [ ] ≥ 8 options across ≥ 4 types, none presented as offers
- [ ] 2–3 packages with give/get and validator results
- [ ] Concession ladder with reciprocal asks that never crosses a confirmed limit
- [ ] Prep Brief contains §10.2 sections; Live Card fits one screen
- [ ] Every section supports My Judgment, status, pin, and live notes
- [ ] ZH intent → up to three editable English variants with back-translation
- [ ] Counterpart ZH/EN input → bilingual reply draft
- [ ] Risk flags cover disclosure, unconditional concession, new commitments, contested-fact assertions
- [ ] Nothing is auto-sent
- [ ] Inferred content, reading risks, and unconfirmed limits are clearly labeled
- [ ] Brief markdown and case JSON export
- [ ] Fake mode runs the full pipeline offline
- [ ] One live smoke test completed with a real key
- [ ] README covers install, env vars, tests, privacy, course policy, cost limits

## 15. Milestones

See `docs/TASKS.md`. Summary: M1 shell and models · M2 PDF ingestion · M3 organization and extraction · M4 analysis layer part 1 (interests, positions, islands) · M5 analysis layer part 2 (walk-away, limits, options, packages) · M6 Brief and notes · M7 live workspace and language assistant · M8 verification.

## 16. P1 backlog (do not build in v1)

1. Offer/package evaluator with confirmed-constraint checking and numeric scoring.
2. Weighted multi-issue utility scores.
3. ZOPA estimation and visualization when information suffices.
4. 5–12 round AI-simulated negotiation.
5. Automatic extraction of offers, concessions, and tentative agreements from live conversation.
6. Behavior-based debrief.
7. Multi-session archive, delete, and versioning.
8. Line-level PDF result editing, advanced table reconstruction, rotation, image enhancement.
9. Local PDF fallback parsing and batch multimodal cost optimization.
10. Richer timelines, event graphs, cross-version diffs.
11. Full ZH/EN UI switching.
12. Speech transcription, auto-listening, post-negotiation review.
13. Separate frontend, accounts, cloud sync, plugin/skill packaging.

None of these may weaken: traceable evidence · labeled inference · visible reading risk · human-correctable chronology · user-confirmed limits · scope filtering before use.

## 17. Deliverables and demo

**Deliverables:** runnable Streamlit app; full source with Pydantic models; PDF ingestion and relationship pipeline; the §8 analysis layer; Living Brief with section notes; ZH→EN and bilingual reply features; OpenAI and fake clients; prompts and fixtures; automated tests; a worked Simulation 1 example; README, `environment.yml`, `requirements.txt`, `.env.example`, `.gitignore`; a 2–3 minute demo script.

**Demo script:**
1. Upload a representative Simulation 1 PDF.
2. Show native vs AI-assisted routing.
3. Open the reading result; verify a date, a number, and a table relation.
4. Show the system judging the materials complementary/thematic rather than forcing a timeline.
5. Optionally show the temporal fixture with misleading filenames and body-driven ordering.
6. Review per-document summaries and structured JSON.
7. Expand one issue's evidence and correct one AI field.
8. Show consolidated conflicts and unknowns.
9. **Open Strategy Lab: NFMV for both sides, one reframe question, the islands-of-agreement board with one contested item and its verification question.**
10. **Show the walk-away tab: BATNA, reservation derivation, triggers, exit script.**
11. **Confirm one redline, demote one candidate to a bottomline, and show the difference.**
12. **Show the option inventory, build a package, and trigger a validator warning by including a redline-crossing option.**
13. Generate the Prep Brief and switch to the Live Card.
14. Write My Judgment and a live note in two sections; switch to pinned-only.
15. Enter a Chinese intent; show three English variants with back-translation.
16. Paste a counterpart statement; show the bilingual draft and a risk flag.
17. Save a draft as a note and export markdown + JSON.

**Done means the pipeline is stable, transparent, and demoable on real Simulation 1 materials — not that the feature count is high.**
