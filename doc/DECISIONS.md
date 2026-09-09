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
  the "Evidence or nothing" invariant in CLAUDE.md (document_id + page/paragraph
  + excerpt for every non-inferred claim).
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
