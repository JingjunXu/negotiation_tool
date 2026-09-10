# DECISIONS.md — decisions made while the SPEC was ambiguous

Per CLAUDE.md §5: when the SPEC is ambiguous, pick the option that keeps
evidence traceable and human judgment authoritative, and record the decision
here.

## Repo layout: `doc/` vs `docs/`

CLAUDE.md and SPEC.md refer to `docs/SPEC.md`, `docs/TASKS.md`, `docs/DECISIONS.md`,
but the checked-in folder is `doc/`. Kept the existing `doc/` folder rather than
renaming it, and put this file at `doc/DECISIONS.md`. Treat `docs/` in prose
elsewhere as referring to this same folder.

## T1.3 — models "retained from v1" that SPEC v2 does not print

SPEC v2 §9 says `Evidence`, `ReviewedText`, `DocumentRecord`, `NegotiationIssue`,
`Constraint`, `Deadline`, `Conflict`, `OpenQuestion`, `NegotiationCase` are
"retained" from a v1 spec that is not present in this repo. They were
reconstructed from how v2 uses them elsewhere in the document:

- **Evidence** — `document_id`, `page_number`, `paragraph_id`, `excerpt`, matching
  the "Evidence or nothing" invariant in CLAUDE.md (document_id, page/paragraph,
  and excerpt for every non-inferred claim).
- **ReviewedText** — a generic "claim with epistemic status + evidence + user-edit
  tracking" building block: `current_value`, `ai_original_value`,
  `evidence_status` (the shared `explicit|inferred|unknown|user_confirmed`
  literal), `evidence`. Reused everywhere §9's pseudocode already types a field
  as `ReviewedText` (e.g. `InterestItem.statement`, `Redline.statement`,
  `Bottomline.threshold_value`) and also for case-level extracted fields
  (`my_role`, `context`, `objective`, `batna`, etc.) so every extracted claim in
  the case carries the same edit/evidence contract. No separate `user_edited`
  bool — an edit is detectable by comparing `current_value` to
  `ai_original_value`, so a second flag would be redundant state.
- **DocumentRecord** — fields taken directly from the §4.1 per-material record
  list (document_id, filename, upload_index, file type/size, SHA-256,
  page/paragraph count, parse method, per-page reading method, pages needing
  review, scope, processing status, warnings).
- **NegotiationIssue** — fields inferred from the Issue Map Brief section
  (§10.2 #11: target, acceptable range, priority, flexibility, status) plus a
  title and both parties' stated positions as `ReviewedText`.
- **Constraint** — modeled as the *raw, pre-classification* candidate limit
  that `classify_constraints` (T5.2) turns into `Redline`/`Bottomline`
  candidates. Deliberately thin (statement + source_type + evidence) since
  the real structure lives in `Redline`/`Bottomline`.
- **Deadline** — `date_text` keeps the date as written (never force a strict
  date type when the source text is relative or approximate, per the
  "keep units as text" pattern used for `Bottomline.threshold_value`);
  `normalized_date` is an optional ISO date filled in only when unambiguous.
- **Conflict** — holds a list of `ConflictingValue` (document_id + value +
  evidence) rather than a single free-text description, so every conflicting
  number keeps its own citation. `AgreementItem.conflict_id` (§8.3) links here.
- **OpenQuestion** — `question` + optional `context` + related documents +
  evidence.
- **NegotiationCase** — assembled from the §7.2 extraction field list (my/counterpart
  role, context, objective, interests, positions, BATNA, issues, targets,
  hard constraints, authority limits, deadlines, possible concessions,
  counterpart information, open questions, evidence, conflicts, warnings),
  plus `documents` and `organization` (produced upstream by ingestion/§6), plus
  `analysis: NegotiationAnalysis | None` per §9. `analysis` is optional because
  the case exists (post-consolidation) before the analysis layer runs.

These are implementation choices, not SPEC content — if a later task's fixture
needs a field these definitions don't have, extend the model rather than
inventing new negotiation content to fit the current shape.

## T2.1 — "per-file and total size" with only one size env var

SPEC §4.3 says to validate "per-file and total size," but §13.4 only defines
one size knob, `MAX_UPLOAD_MB`. Rather than invent a second env var not in the
SPEC, `document_parser.validate_upload` applies `MAX_UPLOAD_MB` as both: the
cap on any single file, and the cap on `running_total_bytes + len(data)`,
where `running_total_bytes` is a running tally the caller (the future
Materials page, T2.1's UI counterpart is not yet built) is expected to pass
in as it accepts files one by one in a session.

## T3.2 — added `confidence` and `rationale` to MaterialOrganizationResult

SPEC §6.2 phase B explicitly requires an overall `high|medium|low confidence`
and "a short user-facing rationale (no hidden reasoning stored)" as part of
the cross-document organization output, but the pydantic snippet in §6.4 only
printed `organization_mode` through `review_status` — no `confidence` or
`rationale` field. Added both as fields on `MaterialOrganizationResult`
(`confidence` required-with-default `"low"`, `rationale: str = ""`) since the
UI (T3.3) and SPEC §14.1 item 8 ("low confidence organization requires user
confirmation") depend on there being a real confidence value to gate on. Both
additions are backward compatible (existing constructions default sanely).

`material_organization_service.organize_materials` also defensively forces
`confirmed_order=None` and `review_status="unreviewed"` on whatever any
AIClient returns — organization must never be auto-confirmed by AI (SPEC
§6.3), the same pattern used for redlines.

## T3.4 — FakeAIClient.extract_document only surfaces pattern-matched facts

Unlike relationship-cue extraction (dates, version markers — syntactically
regular), fields like objective, BATNA, positions, and interests are
semantic judgments a rule-based fake client cannot make honestly. So
`FakeAIClient.extract_document` only ever returns: summary bullets built
from real cue excerpts (or, failing that, the document's first few literal
sentences), `role_and_purpose` from the same document-role keyword match
used for cues, deadlines where a date cue sits near a deadline-ish keyword
("due", "deadline", "by the"), and open questions that are literal
sentences ending in "?". Every other field (`my_role`, `counterpart_role`,
`objective`, `batna`, `interests`, `positions`, `issues`,
`hard_constraints`, `authority_limits`, `possible_concessions`,
`counterpart_information`) stays `None`/empty — guessing them would violate
"never invent negotiation content" even though it's tempting to fill every
field for a nicer fake-mode demo. `OpenAIClient.extract_document`, by
contrast, can fill all of these because a real model reads with actual
comprehension; both normalize through the same
`ai_client.document_extraction_from_draft` so the two routes stay identical
in shape.

## T3.5 — consolidate_case returns a plan, not a NegotiationCase

SPEC §13.1 sketches `consolidate_case(request) -> NegotiationCase`, but
letting a model directly emit the entire consolidated case would mean the
model re-transcribes every ReviewedText, evidence entry, and conflict —
exactly the content whose integrity matters most in this app. Instead,
`AIClient.consolidate_case` returns a `ConsolidationPlan` (only: which
issues across documents are duplicates of each other). All merge
arithmetic — unioning evidence, detecting divergent values, building
`Conflict` records, never silently overwriting one document's number with
another's — is deterministic code in `consolidation_service.py`. This is
also why `merge_reviewed_texts` passes a single-source value through
*unchanged* (same object) rather than reconstructing an equivalent copy:
identity preservation is the strongest possible guarantee that
`ai_original_value` (SPEC item 11) survives consolidation untouched.

Added `document_extractions: list[DocumentExtraction]` to `NegotiationCase`
so per-document extractions remain inspectable after consolidation (SPEC
§7.3: "Keep both per-document and consolidated results for pipeline
display"), mirroring the earlier `relationship_cues` addition.

## T4.1 — counterpart interests use a separate API call with a pre-filtered context

SPEC §8.1's confidentiality rule ("counterpart items may only be derived
from shared/instructor_rules materials... never claim knowledge of their
confidential brief") is enforced structurally, not just by prompt wording:
`interest_service.build_interest_context` builds two separate context
bundles from the case — `my_context` (everything) and `counterpart_context`
(only evidence whose `document_id` belongs to a `shared`/`instructor_rules`
document) — and `OpenAIClient.analyze_interests` makes two *separate*
`responses.parse` calls, one per party, each seeing only its own bundle. A
single combined call could technically let the model cross-reference the
"my interests" section while writing about the counterpart even with an
instruction not to; two calls make that impossible because the confidential
text is never present in the counterpart call's input at all.

`interest_service.analyze_interests` also defensively re-forces
`is_hypothesis` from `party` after the call returns (never trusts the
client), matching the same "AI cannot self-certify a safety-relevant flag"
pattern used for redlines and organization confirmation.

FakeAIClient's version of this call only relabels already-evidenced
`Constraint` objects as `need` interests — it does not attempt fears,
motives, values, or any counterpart items, since those require real
language understanding a rule-based fake client cannot supply honestly
(same reasoning as T3.4).

## T4.2 — position-interest linking uses issue positions, not the flat `case.positions` list

`case.positions: list[ReviewedText]` (from T1.3's reconstruction) carries no
party tag, but SPEC §8.2 needs "mine or theirs" for every position. The
model *does* have party-attributed positions already: `issue.my_position`
and `issue.counterpart_position`. `interest_service.map_positions_to_interests`
builds its input from those instead. The flat `case.positions` list stays a
general-purpose bucket shown as-is on the Negotiation Map page; it just
isn't part of the interest-linking flow. Lives in `interest_service.py`
rather than a new module, matching CLAUDE.md's repo map (no separate
"position service" file is listed).

Also defensive, matching the pattern used everywhere else: the service
never trusts the AI for `party` or `stated_position` (both come from the
service's own `PositionToMap` records, keyed by `ref`) and filters
`underlying_interest_ids` against the real interest id set before
constructing any `PositionInterestLink` — satisfying SPEC's requirement that
every link resolves to an id that actually exists.

## T4.3 — "shared" is a structural check, not a trusted AI label

Same defense-in-depth pattern as T4.1: the prompt tells the model the rule
("a claim whose only evidence is from a `my_confidential` document must
never be `shared`"), but `agreement_service.analyze_agreement_landscape`
also re-checks every item's evidence document scopes in code and downgrades
`standing` to `"unverified"` if none of it traces to a `shared`/
`instructor_rules` document — regardless of what the model returned. Also
enforced in code, not just prompted: every non-`shared` item gets a
`verification_question` (synthesizing a generic one if the model omitted
it), and `conflict_id` is dropped unless it matches a real id in
`case.conflicts` (never lets the AI reference a conflict it invented).

FakeAIClient's version only turns existing `Conflict` records into
`"contested"` items — a structurally-verified disagreement is the one thing
it can report honestly without language understanding; it makes no attempt
at shared/unverified classification over free text.

## T4.4 — Strategy Lab never offers a "promote to shared" action

`AgreementItem` (SPEC §9) has no `confirmed_by_user` flag the way
`Redline`/`Bottomline` do, so "cannot be confirmed as shared without user
action" (TASKS.md T4.4) is satisfied by omission: the Agreement Landscape
board is read-only per standing (three columns, visually distinct via
color/emoji), and there is no button anywhere that moves an item into the
`shared` column — only the code-enforced scope rule in agreement_service.py
can produce that label. If a future task adds user override of standing,
it should go through the same `model_copy(update=...)` + preserved-original
pattern used everywhere else, not a silent reclassification.

## T5.2/T5.3 — constraint confirmation stays 100% user-driven

`Redline.confirmed_by_user` and `Bottomline.confirmed_by_user` are set
`False` unconditionally whenever `constraint_service.classify_constraints`
builds candidates from an AI draft — the draft schemas
(`AIRedlineDraft`/`AIBottomlineDraft`) don't even have a confirmation field
for the AI to set. In the Strategy Lab Limits tab, only an explicit
"Confirm" button click sets it `True`; demote/promote reset it `False`
(different assertion, needs fresh confirmation) and always route through
`constraint_service.demote_redline_to_bottomline`/
`promote_bottomline_to_redline`, which pass the same `ReviewedText` object
through unchanged so `ai_original_value` survives the conversion exactly
(SPEC item 21).

`Bottomline.provisional` is likewise computed in code, not trusted from the
AI: `is_really_linked = has_usable_batna and bool(linked_batna_reference)`
— even if the model claims a `linked_batna_reference`, it's discarded
unless the case actually has a usable `estimated_reservation_value` (SPEC
item 19).

Added a "Run walk-away analysis" button to the Strategy Lab Walk-Away tab.
No TASKS.md entry explicitly assigns wiring that tab (T4.4 only covers
tabs 1-2), but constraint classification needs `analysis.walk_away` to
exist for its BATNA-link check to mean anything, so this small addition
was necessary to make T5.2/T5.3 usable end-to-end.

"Reject" for a redline/bottomline candidate means removing it from the
list — neither model has a `rejected` status field (unlike
`NegotiationOption`), so there's nothing to flip; the candidate simply
stops being tracked and can never reach the Brief.

## T5.4 — FakeAIClient generates real options, unlike other fake-mode stages

Every other FakeAIClient method in this codebase deliberately withholds
semantic content it can't produce honestly (T3.4, T4.1, T4.3, T5.2). Options
are the one stage where that restraint doesn't apply: SPEC's own vocabulary
defines an Option as "an invented possibility, not yet evaluated" —
invention is the explicit purpose of §8.6, not a violation of "never invent
negotiation content." That invariant is about factual claims (dates,
amounts, who-said-what) presented as evidenced; a brainstormed option
linked to a real interest id and never asserted as agreed is exactly what
the stage is supposed to produce. So `FakeAIClient.generate_options` uses
eight generic templates (one per `option_type`) that assert no case-specific
fact, each linked to a real "me"/"counterpart" interest id — giving fake
mode genuine ≥8-options-across-≥4-types coverage (SPEC item 22) instead of
an empty inventory.

`option_service.generate_options` always returns only the *newly* generated
batch — "Generate more options" appends without discarding (TASKS.md T5.4)
by the caller doing `analysis.options.extend(new_options)` rather than this
function pre-merging; the existing options' titles are still passed to the
AI request so it can avoid pure repeats.

## T5.5/T5.6 — validator lives in package_service.py; number/direction parsing is heuristic

TASKS.md lists T5.6 ("Limit validator, pure function") as its own task but
names no separate module for it, and CLAUDE.md's repo map has one
`package_service.py` covering all of M5's packaging concerns — so
`validate_against_limits` (SPEC's exact signature: `package | ladder,
redlines, bottomlines -> list[warning]`) lives there, built alongside T5.5
since package/ladder construction calls it directly (to stop a concession
ladder before it would cross a confirmed limit, not just report the
crossing after the fact).

Two structural guarantees now live at the **model** level, not just the
service: `ConcessionStep.ask_in_return` and `HagglePlan.justification_standard`
each got a `field_validator` rejecting blank/whitespace-only values — this
makes SPEC items 25 (non-empty `ask_in_return`) and 26 (anchor requires a
justification standard) impossible to violate anywhere in the codebase, not
just when going through `package_service`. `package_service.build_haggle_plan`
raises `ValueError` early with a clear message if the AI left
`justification_standard` blank, rather than letting a generic
`ValidationError` surface from deep inside model construction.

Bottomline crossing uses the structured `direction`/`threshold_value`
fields directly (clean boundary semantics: sitting exactly at the
threshold is not a crossing). Redlines have no such structured threshold,
so `_text_crosses_redline` best-effort parses a number and a direction
keyword (e.g. "beyond", "under") out of the redline's own statement text
and compares it to a number parsed from the package/step text — this is a
heuristic, not real language understanding, and by design returns "no
crossing" (never a false positive) whenever either number or the direction
can't be confidently parsed. `TradeCurrency` computation is plain code
(SPEC: "derived from option costs and interest matches" — mechanical, no
AI judgment needed): "i_can_give" from low/medium-`cost_to_me` options,
"i_want_to_get" from my own interests.

FakeAIClient's haggle plan mechanically groups real options into 2-3
packages (equivalence explicitly marked unverified), returns an **empty**
concession ladder rather than inventing plausible numbers with no basis,
and uses six generic (fact-free) counter-tactic lines — the same
"invention is fine, fabricated facts are not" line drawn in T5.4, except
here the anchor/ladder genuinely would require external market knowledge
the fake client doesn't have, so it declines rather than guessing.

## T5.7 — package/ladder warnings are re-computed live, not cached

"Package builder showing live validator warnings" (TASKS.md T5.7) is taken
literally: the Options & Packages tab calls
`package_service.validate_against_limits` again at render time for every
package and for the whole concession ladder, rather than only trusting the
`validator_warnings` snapshot captured when the plan was first built. This
matters because confirming or demoting a redline/bottomline in the Limits
tab (T5.3) changes what counts as "confirmed," and a stale snapshot would
show an outdated (or missing) warning after that. The pure function is
cheap enough to call on every rerun.

"Generate more options" is one button, not two: it always calls
`option_service.generate_options(..., existing_options=analysis.options)`
and extends the list, so first-generation and incremental generation are
the same code path — simpler than a separate "first run" affordance, and
matches "appends without discarding" exactly regardless of how many times
it's clicked.

Initially wired option/case context into the options tab via module-level
globals to avoid threading parameters through helper functions — caught
and fixed before landing: Streamlit reruns one script per session, but
module-level state in a plain Python module is process-wide, so that would
have leaked state between concurrent users. Fixed by passing `case` and
`ai_client` as explicit parameters throughout.

## T6.1/T6.2 — Brief assembly is almost entirely code; added NegotiationBrief and LiveCard models

SPEC never prints a `NegotiationBrief` or `LiveCard` model despite naming
them throughout §10. Added both: `NegotiationBrief` is just
`sections: list[BriefSectionState]` (18 entries, one per §10.2 row) +
`generation_notes: list[str]`, reusing the §11.4 `BriefSectionState`
directly since it already has exactly the "AI base + evidence + status +
pin + notes" shape §10.4 describes. `LiveCard` is a fixed-shape compressed
view (SPEC §10.1's own field list: walk-away line, redlines, top-3
interests per side, shared-facts opener, packages, next questions, pinned
sections).

All 18 Brief sections are assembled by plain code directly from the
case/analysis/haggle-plan — evidence and confirmation gates (redlines,
bottomlines) must never pass through a model call that could paraphrase or
drop them. The **only** AI call (`generate_brief`/`BriefProseDraft`) writes
a handful of short prose pieces (case summary, objective summary, success
criteria, opening plan, question phrasing) from a context that is itself
built by code — never asked to touch limits, options, or packages. This
mirrors the T3.5/T5.5 pattern of "AI proposes narrow synthesis, code
assembles the safety-critical parts."

`_redlines_section`/`_bottomlines_section` filter to `confirmed_by_user`
and log an excluded-count note; `_uncertainties_section` is where every
unconfirmed candidate reappears, satisfying both halves of SPEC item 20
(never a hard limit in its own section, never silently dropped either).

`build_live_card` takes an optional `brief` parameter rather than always
requiring a fresh `NegotiationBrief` — it reuses the Brief's already-curated
question phrasing and pinned sections when one is available, but can also
render walk-away/redlines/interests/islands/packages standalone from just
the case, since those don't need the prose stage at all.

FakeAIClient's `generate_brief` composes case_summary/objective_summary/
opening_plan mechanically from real case fields (never invents wording it
can't ground), consistent with the fake-mode honesty policy established in
T3.4/T4.1/T5.1/T5.5.

## T6.3 — the Brief is a session_state sibling of the case, not a case field

`NegotiationBrief` is defined after `NegotiationCase` in models.py (it
belongs with the §11.4 block), so it can't be a typed field on
`NegotiationCase` without a forward-reference/`model_rebuild()` dance. Since
the Brief is a *derived*, regenerate-on-demand artifact — not extracted
case content — it lives in its own `st.session_state["brief"]` key
(`pages/_common.get_brief`/`set_brief`), the same pattern already used for
`ai_client`. `brief_service.build_live_card(case, brief)` takes the brief
as an explicit optional argument rather than reading it off the case.

Notes autosave per-section as their own JSON file under
`APP_DATA_DIR/cases/<case_id>/brief_sections/<section_id>.json`
(`note_service.autosave_section`/`load_section_state`) rather than one file
for the whole brief, so saving a note on section A never rewrites section
B's file. This is deliberately a *durability* backstop for note text
specifically (SPEC's explicit "autosave... under APP_DATA_DIR" requirement)
— the authoritative in-session copy is still the `BriefSectionState` object
inside `st.session_state["brief"]`; nothing currently reads the on-disk
copy back on a fresh session (no cross-session case resume exists yet in
this app), so `load_section_state` is exercised by tests but not yet wired
into page load. Wiring that up is future work if/when the app gains
case-resume, not something T6.3 itself needed.

`promote_note_to_case` picks the least-committal outcome for each target
type on purpose: `redline_candidate`/`bottomline_candidate` are created
with `confirmed_by_user=False` (so the existing Limits-tab confirm action
is still required — see T5.2/T5.3), and `agreement_item` is created at
`standing="unverified"` (never `"shared"`, which has its own stricter
scope-evidence gate from T4.3). This is what makes SPEC item 32 ("a note
never becomes a confirmed fact... by itself") true regardless of which
target the user picks.

The Brief Builder page's inline "carry notes/status/pin forward by
section_id on regenerate" is a minimal version of full stale-marking;
T6.4 is where `stale=True` gets set deliberately when specific inputs
change, rather than always silently reusing whatever the previous section
happened to contain.

## T6.4 — per-section fingerprints, not a single case-wide hash

Added `BriefSectionState.source_fingerprint: str | None` to make staleness
granular rather than all-or-nothing. `brief_service._section_source_data`
maps each of the 18 section ids to the exact slice of case/analysis data it
was built from (e.g. `redlines` section depends only on
`analysis.redlines`; `issue_map` only on `case.issues`), and
`refresh_staleness` recomputes each section's fingerprint and flips
`stale=True` only where it changed. A single combined hash would have been
simpler but would mark all 18 sections stale on any edit anywhere, which
contradicts SPEC's own wording: "editing the case or organization marks
**affected** AI bases stale," implying the rest stay trustworthy. The two
prose-only sections (`questions_to_ask`, `opening_plan`) have no tracked
fingerprint — nothing about them lets you say "line 3 of this paragraph
depends on redlines," so their freshness is only ever restored by an
explicit full regeneration, not tracked incrementally.

`refresh_staleness` never touches `notes`, `status`, or `pinned` — it only
ever sets `stale`, keeping it orthogonal to the human-content-preservation
guarantee from T6.3/item 28.

## T7.1-T7.3 — risk flags are computed by code, never trusted from the model alone

Built T7.1 (ZH→EN phrasing), T7.2 (bilingual reply), and T7.3 (the full
§11.3 risk-flag set) together in one `language_service.py`, since the risk
checker is shared by both language modes and there's no way to test T7.1's
"preserves numbers/conditions/negations" requirement meaningfully without
it. `check_risk_flags` is a pure function (no AI) that re-derives every
flag from the case's *confirmed* data:

- `reveals_batna`/`reveals_reservation_value`/`reveals_bottomline`/
  `crosses_redline`: literal substring match of the draft against
  `walk_away.my_batna`/`estimated_reservation_value`/confirmed
  `Bottomline.threshold_value`/confirmed `Redline.statement`. Unconfirmed
  redlines/bottomlines are excluded on purpose — SPEC never treats an
  unconfirmed candidate as a hard limit, so it can't leak a limit that
  doesn't officially exist yet.
- `contradicts_confirmed_field`: reuses `package_service.extract_number`
  (renamed from `_extract_number`, now a shared cross-module utility) to
  check whether a *new* number in the draft numerically crosses a confirmed
  bottomline's threshold — catches disclosure risks a literal-text match
  would miss (e.g. draft says "$80,000", bottomline says "$100,000").
- `asserts_contested_fact_as_agreed`: literal match against any
  `contested`/`unverified` (never `shared`) agreement-landscape statement.
- `new_commitment`/`unconditional_concession`: diff the numbers in the
  draft against the numbers in the user's own `user_input`; a new number
  with no conditional marker ("if", "provided that", "in exchange"...)
  nearby trips both.

The AI's own self-reported `risk_flags` (each prompt asks for them) are
kept, not discarded — `phrase_in_english`/`draft_bilingual_reply` return
the *union* of the model's flags and the code-checked ones, so a model
catching something code-heuristics can't (subtler disclosure phrased
without literal text overlap) still surfaces.

`build_language_context` hard-excludes `walk_away_position`, `redlines`,
and `bottomlines` from the context sent to the model, even if the user
explicitly selects one of those Brief sections — quoting the private
content into the prompt would be a disclosure risk on its own, instruction
or not. Caught and fixed during review: an earlier draft only read
`case.context`/`case.objective` and silently dropped the user's brief
section selection entirely (`selected_brief_section_ids` was received but
never used) — fixed to thread an optional `brief` through so selected
non-private sections are actually included.

FakeAIClient's phrasing/reply methods say plainly that automatic
translation is unavailable rather than echoing the input back labeled as
if it were a real English draft — same honesty policy as every other
fake-mode method in this codebase.

## T7.4 — "sticky header" is a static top block, not real CSS-sticky positioning

SPEC's "sticky header" for the Live Workspace (§12 Page 6) is approximated
as a normal block at the top of the page (walk-away triggers + confirmed
redlines, always rendered before the two columns) rather than actual
scroll-sticky CSS, since Streamlit's native layout API has no supported
sticky-position primitive without injecting raw HTML/CSS outside the
framework's component model. The content and warning semantics are real;
only the "stays pinned while scrolling" visual behavior is not.

"Save as note" originally hardcoded an arbitrary target section per mode
(e.g. always "opening_plan" for Mode A) — caught on review as making no
real sense (why would a ZH→EN phrasing draft always attach to the opening
plan specifically?) and changed to a selectbox so the user picks which
Brief section a saved draft becomes a live note under, consistent with
notes always being explicit, user-directed actions elsewhere in this app.

Live history uses the real `LiveInteraction` model (§11.4) rather than a
plain dict, stored in `st.session_state["live_history"]`— local only,
clearable via one button, never persisted to disk (unlike Brief notes,
which explicitly need APP_DATA_DIR autosave per T6.3; live interaction
history has no such requirement in SPEC).

## T2.3 — OpenAIClient.read_pdf is unverified against the live API

`ai_client.py`'s `OpenAIClient` uses `client.responses.parse(..., text_format=AIPageReadingBatch)`
(direct PDF file input first, PyMuPDF-rendered-page vision input as a fallback
triggered by `openai.BadRequestError`), matching the openai==1.109.1 SDK
surface inspected in this environment. No `OPENAI_API_KEY` is available in
this session, so the request-building and response-normalizing logic is unit
tested with a mocked `responses.parse`, but the actual round trip against the
live API has never run. Run the T8.4 live smoke test (SPEC §14.3) before
trusting this path, and if the SDK/API shape has since changed, treat this
implementation as the first thing to check.

## T2.1 — validate_upload is the single safety gate for all file types

`document_parser.py` owns `validate_upload` (extension allowlist, magic-byte
sniffing against claimed extension, executable/script detection, path
traversal, size) for every accepted type including PDF, even though PDF
parsing itself lives in `pdf_ingestion.py` (T2.2). This avoids duplicating
the safety checks in two modules; `pdf_ingestion.py` will call
`document_parser.validate_upload` before doing any PDF-specific work.

## T8.5 follow-up — Materials page was never wired to real uploads

Discovered during the T8.5 SPEC §14.4 acceptance-checklist pass: `pages/materials.py`
was still the T1.4 placeholder — it only rendered whatever was already in
`case.documents` (the demo fixture) and had no `st.file_uploader`, no paste-text
input, and no call into any ingestion/organization/consolidation service. Every
service the Materials page needs (`document_parser`, `pdf_service`,
`material_organization_service`, `consolidation_service`) was already built and
unit-tested from M2/M3, but nothing in the UI layer ever called them for a real
upload. Not caught earlier because T3.3/T3.6 built the *downstream* organization
and negotiation-map UIs against the demo fixture case, and the fake end-to-end
test (T8.2) exercises the same services directly rather than through the page.

Fixed by adding `negotiation_copilot/ingestion_service.py` — a thin
"validate → route to `pdf_service` or `document_parser` → extract relationship
cues → extract per-document structured extraction" orchestration function
(`ingest_material`), kept out of the page module for the same reason prompts
are kept out of page code (CLAUDE.md: "Do not build prompts inside Streamlit
page code" — the same argument applies to pipeline orchestration, and it makes
the function testable without Streamlit; see `tests/test_ingestion_service.py`).
`pages/materials.py` was rewritten to add a multi-file uploader, a paste-text
form, a per-file scope selector, a "Process" action that calls
`ingest_material` and appends to `case.documents` /
`case.relationship_cues` / `case.document_extractions`, and an "Organize +
Consolidate" action wired to `material_organization_service.organize_materials`
and `consolidation_service.consolidate_case` that replaces the working case.

One follow-on decision: the demo fixture case (`fixtures.sample_case()`,
seeded by `pages/_common.get_case()`) already contains one document. Appending
real uploads onto that document's list would silently mix demo content into a
real case during organization/consolidation. Added `is_demo_case()` /
`set_case()` to `pages/_common.py`, tracked via a `case_is_demo` session-state
flag set on fixture seeding and cleared on any `set_case()` call; the Materials
page checks it before the *first* real ingestion in a session and swaps in a
fresh empty `NegotiationCase()` first, rather than extending the demo case.

Verified against the real `0902files/` materials the user supplied for
testing: all 25 PDFs ingest, organize, and consolidate through
`ingest_material` → `organize_materials` → `consolidate_case` with zero
exceptions and zero pages flagged `needs_review` in fake mode.

## Post-T8.5 — `claude_cli_client.py`: an opt-in backend outside the fixed stack

CLAUDE.md fixes the stack as "OpenAI Python SDK (Responses API)". This
section documents a deliberate, user-requested deviation from that, added
after the build was otherwise complete — not a P0 SPEC requirement, and not
what a course submission should be graded against.

**Why:** the user's `OPENAI_API_KEY` repeatedly failed authentication (401
`invalid_api_key`, confirmed even after they re-copied it from the OpenAI
dashboard) and they had no separate Anthropic Console API key either. They
asked whether the AI calls could instead go through "the current chat
window" — i.e. reuse whatever this Claude Code session is already
authenticated with, rather than a portable API key.

**What was ruled out first:** the Claude Code session's own login is an
OAuth/subscription credential, not an `ANTHROPIC_API_KEY` — it cannot be
extracted and handed to the `anthropic` Python SDK, and doing so would not
be a legitimate use of that credential anyway. Confirmed no
`ANTHROPIC_API_KEY` exists in the shell environment before ruling this out.

**What actually works:** the `claude` CLI itself supports a documented,
intended-for-scripting mode: `claude --print --output-format json
--json-schema '<schema>' --tools ""`. This authenticates however `claude`
is already logged in (no API key needed), and `--json-schema` forces
structured output that round-trips through arbitrary JSON Schema —
including the `$defs`/`$ref`-heavy schemas Pydantic v2 generates for the
existing nested Draft models (`AIReviewedText`, `Evidence`, etc.) — verified
directly against the real CLI before writing any client code. Cost is
attributed to the user's own Claude usage, not a separate bill; a single
text-generation call cost roughly $0.004–$0.01 in testing.

**Design:** `ClaudeCliClient` (in its own module, not added to
`ai_client.py`) implements the same `AIClient` Protocol and reuses the
exact same `prompts/*.md` instructions, request/Draft models, and
normalization helpers as `OpenAIClient` — `relationship_cues_from_batch`
and `organization_result_from_draft` were extracted out of `OpenAIClient`
into shared module-level functions in `ai_client.py` specifically so both
backends normalize identically instead of drifting. The one method-by-
method difference is `read_pdf`.

**Why `read_pdf` is NOT implemented via this backend:** tested giving the
CLI subprocess the "Read" tool (so it could read a PDF file directly,
Claude's native multimodal PDF understanding) — this required either an
interactive permission grant (impossible for a button-triggered,
unattended call) or `--permission-mode bypassPermissions`, which Claude
Code's own auto-mode classifier correctly flagged and blocked as a risky
pattern when tested. It also cost roughly 100x more per call in testing
(~$0.51 vs ~$0.004) and hit a same-machine sandbox permission denial on a
file outside the invoking process's allowed directories. Rather than bake
an unattended permission-bypass into the pipeline to chase this, `read_pdf`
under this backend always returns every requested page as `needs_review`
with `quality_flags=["claude_cli_no_pdf_reading"]` — the same honest
"can't safely do this, don't fabricate" placeholder FakeAIClient already
uses for its `fake_mode_no_ai_reading` case. This is a real gap only for
pages native `pypdf` extraction can't already handle; verified this is
rare in practice — all 25 real `0902files/` PDFs extract fully natively
with zero pages needing any AI-assisted reading at all.

**How it's selected:** a new `AI_PROVIDER` env var (`config.py`), not part
of SPEC §13.4. Left unset (`"auto"`, the default), behavior is byte-for-byte
identical to before this change — OpenAI if a key is configured, fake mode
otherwise — so nothing changes for anyone who doesn't opt in.
`AI_PROVIDER=claude_cli` switches `pages/_common.get_ai_client()` to
`ClaudeCliClient`, resolving the `claude` executable via `CLAUDE_CLI_PATH`,
`shutil.which("claude")`, or the default Claude Code CLI install location
(`~/.local/bin/claude`), in that order.

**Batch-upload crash found in real use, fixed:** processing a few dozen real
PDFs in one Materials-page click hit a real `ClaudeCliError` (subprocess
timeout — the CLI took >180s on the largest, most deeply-nested draft
schema, `DocumentExtractionDraft`, for one document) that propagated
uncaught out of `ingest_material` and crashed the whole Streamlit page,
losing the rest of the batch. Fixed at the service layer, not just the page:
`ingest_material` now catches any exception from `extract_relationship_cues`
/ `extract_document` and degrades that one document (empty cues, an empty
`DocumentExtraction`, a warning recorded on the `DocumentRecord`) instead of
raising — the same "don't fabricate, don't crash" honesty pattern
FakeAIClient already uses, just extended to real backend failures too. This
was the correct layer to fix it at (not a page-level try/except) since any
future caller of `ingest_material` gets the same resilience for free. Also
bumped `CLAUDE_CLI_TIMEOUT_S`'s default from 180s to 300s (large schemas
genuinely take longer via this backend than a direct API call), and added a
progress indicator to the Materials page upload loop so a multi-minute
batch doesn't look hung. `UploadRejected` (a validation-time rejection,
before any AI call) is unchanged and still surfaces per-file in the page.

**Interests-analysis context gap found and fixed, in `interest_service.py`
(unrelated to the Claude/OpenAI backend choice — this was a pre-existing
pipeline bug):** the user described giving Claude an entire Google Drive
folder directly and getting a clear picture of every party's interests,
and asked why processing files one-by-one through this app felt thinner.
Investigating: `build_interest_context()` (which builds the prompt for the
actual `analyze_interests` stage that produces needs/fears/motives/values)
only rendered `case.my_role`/`counterpart_role`/`context`/`objective`/
`batna`/`positions`/`possible_concessions`/`counterpart_information`/
`authority_limits` — it never included `case.interests` or `case.targets`,
even though per-document extraction *does* populate both (unioned across
documents in `consolidate_case`, shown on the Negotiation Map page labeled
"Interests (raw, pre-analysis)"). For negotiations built from many direct
role-brief documents (the SPEC's original assumption, and
`tests/test_end_to_end.py`'s fixture), the omitted fields rarely mattered,
since role/objective/context are usually stated explicitly somewhere. For
a negotiation assembled from many *indirect* documents (news articles,
meeting notes, third-party statements — like the user's real `0902files/`
materials) no single document states "my role" or "my objective" in so
many words, but per-document extraction *does* correctly pull out
individual interest-shaped statements (e.g. "the tribal leader values the
community's reliance on HfA's medical support") into `case.interests` —
which then sat there, correctly extracted with evidence, but invisible to
the stage that was supposed to synthesize it. Fixed by adding
`case.interests` (labeled "Raw extracted interest (pre-analysis)") and
`case.targets` to the same context-building loop as the other ReviewedText
list fields — same confidentiality filtering applies automatically since
it goes through the existing `_visible()`/`_filter_reviewed_text` path.
Verified live against the real `claude` CLI backend with a case shaped
like the real scenario (empty role/objective/context, only `interests`/
`targets` populated, mirroring what `0902files/`-style indirect materials
actually produce): before this fix the context would have been empty and
`analyze_interests` would have had nothing to synthesize from; after the
fix it produced a well-grounded need/fear/fear/motive/value set correctly
traceable to the raw extracted evidence.

**Concurrent batch ingestion, `ingestion_service.ingest_materials_batch`:**
the user asked for dozens of PDFs to process in "2-3 minutes" and asked
whether `claude_cli` actually works at all. It does (extensively verified
live above), but the honest answer on timing is that a single real
per-document AI call can itself take anywhere from ~15s to several minutes
(one earlier document's `extract_document` call alone exceeded the old
180s timeout) — no backend makes dozens of *sequential* real LLM calls
finish in 2-3 minutes; that constraint doesn't hold even for a single
slow document.

The one lever that actually helps: every document's two AI calls
(`extract_relationship_cues`, `extract_document`) are independent of every
other document's — nothing about processing document N depends on
document N-1 having finished — so there is no correctness reason to run
them one at a time. `ingest_materials_batch` splits ingestion into two
phases: `_prepare_material` (validate + parse/read — fast, and kept
strictly sequential in upload order because `MAX_UPLOAD_MB`'s running-total
check must see prior files' sizes first) and `_enrich_material` (the two
slow AI calls), and runs the enrich phase for all prepared documents
through a `ThreadPoolExecutor` with a bounded worker count
(`INGESTION_MAX_CONCURRENCY`, default 5 — not SPEC-fixed, tunable). This is
backend-agnostic (works the same for `OpenAIClient`, `ClaudeCliClient`, or
`FakeAIClient`) since it's a property of the calls being independent, not
of which client issues them. Progress is reported via an `on_progress(done,
total)` callback invoked from the *calling* thread only (via
`as_completed`, never from inside a worker thread) so the Materials page
can safely drive a `st.progress` bar from it — Streamlit's own API is not
safe to call from arbitrary worker threads.

Per-document AI-call failures still degrade to a warning on that one
`DocumentRecord` exactly as before (T8.8) — concurrency does not change
that contract, it only changes how many documents are "in flight" at
once. A validation-time rejection (`UploadRejected`) is reported as
`IngestResult.error` and does not stop the rest of the batch, same as the
prior sequential loop.

Verified with a synthetic timing test (`_SlowAIClient`, an artificial
delay before each call) that N documents complete in close to one
document's worth of wall time rather than N times that.

Also verified against 6 real `0902files/` PDFs through the live
`claude_cli` backend, `max_workers=6` (all six launched at once): total
wall time was **333s (~5.5 min) for 6 files**, individual documents
finishing between 155s and 333s. This is a genuine, large improvement
over sequential (6 files × 2 calls at ≥150s each would be 30+ min run one
at a time) — but it also shows individual call latency got *worse* under
concurrent load than the ~15-90s seen in earlier single-call tests (see
prior decision entries), consistent with 6 simultaneous `claude` CLI
subprocesses (each a fairly heavy process on its own) contending for the
same account/rate-limit and local CPU. **Bottom line: concurrency
meaningfully helps, but it does not make "2-3 minutes for dozens of
files" achievable** — that would require roughly 10x more improvement
than concurrency alone can provide, since even the fastest of 6
concurrent documents here took over 2.5 minutes. Told the user this
directly rather than overselling the fix; further reductions would need
to cut the number of real AI calls itself (e.g. merging
`extract_relationship_cues` + `extract_document` into one call per
document), not just how many run at once.

**Test-hermeticity fix uncovered along the way:** setting
`AI_PROVIDER=claude_cli` in this machine's own (gitignored) `.env` — so the
app itself would use it — immediately broke the test suite: every
AppTest-based page test that renders a page and doesn't explicitly override
`ai_client` in session_state (e.g. `test_materials_page.py`'s
organize/consolidate test) picked up the ambient `config` singleton via
`pages/_common.get_ai_client()` and made real, slow `claude` subprocess
calls during `pytest`, exactly the "tests depend on network" failure mode
CLAUDE.md forbids. This risk existed in principle before this change too
(a real `OPENAI_API_KEY` in `.env` would have caused the same problem) but
had apparently never been hit. Fixed generally, not just for this one
case: `tests/conftest.py` now has a session-wide autouse fixture that
monkeypatches `pages/_common.py`'s `config` to force fake mode for every
test, regardless of whatever provider the developer's local `.env`
configures for actually running the app.
