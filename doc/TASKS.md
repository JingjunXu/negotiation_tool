# TASKS.md — build queue

Work top to bottom. One task per session/commit where possible. Each task lists the SPEC sections to read first, the files to touch, and the test that proves it is done. Do not start a task until the previous one's tests pass and `streamlit run app.py` still starts.

Mark tasks `[x]` as you complete them and append anything you decided along the way to `docs/DECISIONS.md`.

---

## M1 — Shell and models

- [ ] **T1.0 Conda environment.** Create `environment.yml` (`name: negotiation_tool`, conda-forge, `python=3.11`, `pip`, `pip: [-r requirements.txt]`) and `requirements.txt` with the SPEC §13.3 library list. Then:
  ```bash
  conda env create -f environment.yml
  conda activate negotiation_tool
  python -c "import streamlit, openai, pydantic, pypdf, fitz, docx; print('ok')"
  ```
  *Done when:* the import check passes and `python -c "import sys; print(sys.prefix)"` ends in `negotiation_tool`. Run every later command in this environment; if a shell loses it, re-activate rather than installing anything globally.

- [ ] **T1.1 Project init.** `.env.example`, `.gitignore` (excluding `.env`, `envs/`, `conda-meta/`, `__pycache__/`, `data/*`), `data/.gitkeep`, package skeleton per CLAUDE.md repo map, `pytest.ini` with a `live` marker. Add the `config.py` startup guard that warns when `sys.prefix` is not the `negotiation_tool` env.
  *Done when:* `pytest` runs with zero failures inside the activated environment, and running it outside the environment prints the guard warning.

- [ ] **T1.2 Config.** `config.py` reads every env var in SPEC §13.3, validates ranges, and exposes `is_fake_mode` when no key is present.
  *Test:* missing key → fake mode; `OPENAI_STORE_RESPONSES=false` → `store=False` in request kwargs.

- [ ] **T1.3 Core models.** All models in SPEC §5.4, §6.4, §9, §11.4 in `models.py`. Pydantic v2, no float coercion of negotiation values.
  *Test:* round-trip serialize/deserialize a fully populated `NegotiationCase` including `NegotiationAnalysis`.

- [ ] **T1.4 Six-page shell.** `app.py` routes to Materials, Pipeline & Relationships, Negotiation Map, Strategy Lab, Brief Builder, Live Workspace (SPEC §12), each rendering a hardcoded fixture case.
  *Done when:* every page renders with no key configured.

## M2 — PDF ingestion and understanding

- [ ] **T2.1 Document parsing.** DOCX/TXT/MD/pasted text → paragraph records with ids. Safety checks per SPEC §4.3.
  *Test:* rejects oversized/executable files; identical hash reuses parse result.

- [ ] **T2.2 Native PDF extraction.** `pdf_ingestion.py`: per-page text with 1-based numbers + a sufficiency heuristic (empty, garbled, low density, table-suspicion).
  *Tests:* SPEC §14.1 items 1–2.

- [ ] **T2.3 AI reading adapter.** `pdf_service.py` + `OpenAIClient.read_pdf` supporting direct PDF/file input, with page rendering only as an internal fallback. Normalize all routes to `PDFPageResult`.
  *Test:* both routes produce identical shape; unreadable regions get `needs_review`, never invented content.

- [ ] **T2.4 Fake reader + resilience.** `FakeAIClient` PDF fixtures, caching, per-page retry, partial-result preservation on API error.
  *Tests:* SPEC §14.1 items 3–4.

## M3 — Organization, extraction, consolidation

- [ ] **T3.1 Relationship cues.** Per-document cue extraction (SPEC §6.2 phase A) with excerpts and page numbers.

- [ ] **T3.2 Organization service.** Mode classification, conditional ordering with evidence priority, groups, confidence, ambiguities.
  *Tests:* SPEC §14.1 items 5–8.

- [ ] **T3.3 Organization UI.** Page 2 per SPEC §6.3 and §12: mode first, order comparison or groups, accept/edit, per-stage JSON expanders.

- [ ] **T3.4 Per-document summary + structured extraction.** SPEC §7.1–7.2, with `explicit/inferred/unknown/user_confirmed` tagging and `null` for absent numbers.

- [ ] **T3.5 Consolidation.** SPEC §7.3: merge issues keeping evidence, create conflicts, no silent supersede, open questions.
  *Tests:* SPEC §14.1 items 9–11.

- [ ] **T3.6 Negotiation Map UI.** Page 3 with evidence viewer and Confirm/Edit/Reject preserving `ai_original_value`.

## M4 — Analysis layer, part 1: understanding the people

Read SPEC §8.1–8.3 before starting.

- [ ] **T4.1 Interest service.** `interest_service.py` + `analyze_interests.md`. Four separate lists per party; counterpart items always `is_hypothesis=True` with a verification question; counterpart derivation restricted to `shared`/`instructor_rules` scopes.
  *Tests:* SPEC §14.1 items 13–14. Also: thin materials produce few items plus open questions, never filler.

- [ ] **T4.2 Positions ↔ interests map.** `map_positions_to_interests.md`. Each link has an inference basis and a reframe question; flag my own position/interest misalignment.
  *Test:* every `PositionInterestLink.underlying_interest_ids` resolves to existing `InterestItem` ids.

- [ ] **T4.3 Agreement landscape.** `agreement_service.py` + `map_agreement_landscape.md`. shared / contested / unverified across facts, values, process; link contested numbers to existing conflicts.
  *Tests:* SPEC §14.1 items 15–17.

- [ ] **T4.4 Strategy Lab tabs 1–2.** Interests grid + positions map; agreement landscape board with verification questions surfaced.
  *Done when:* a contested item is visually distinct from a shared item and cannot be confirmed as shared without user action.

## M5 — Analysis layer, part 2: limits, options, trades

Read SPEC §8.4–8.7 before starting. Order matters: walk-away feeds bottomlines, options feed packages.

- [ ] **T5.1 Walk-away service.** `walkaway_service.py` + `analyze_walk_away.md`: BATNA, quality, improvement actions, reservation value with stated derivation, counterpart BATNA hypothesis + probes, triggers, exit script, `do_not_disclose`.
  *Tests:* SPEC §14.1 item 18. Also: aspiration is never used as reservation value (fixture with an ambitious target and a weak BATNA).

- [ ] **T5.2 Constraint classification.** `constraint_service.py` + `classify_constraints.md`: redline candidates by source type vs bottomline candidates with thresholds, rationale, revisit conditions, BATNA link.
  *Tests:* SPEC §14.1 items 19–21.

- [ ] **T5.3 Limits UI.** Strategy Lab tab: side-by-side immovable vs flexible, confirm / demote / promote / reject, `ai_original_value` preserved, unconfirmed items routed to the Brief's uncertainties section.

- [ ] **T5.4 Option generation.** `option_service.py` + `generate_options.md`. Prompt must explicitly walk the eight heuristics in SPEC §8.6. No evaluation, no rejection, no ranking. "Generate more options" appends without discarding.
  *Tests:* SPEC §14.1 items 22–23.

- [ ] **T5.5 Package + haggle plan.** `package_service.py` + `build_haggle_plan.md`: trade currency table, 2–3 MESOs, anchor with required justification standard, concession ladder with reciprocal asks, counter-tactic playbook.
  *Tests:* SPEC §14.1 items 25–26.

- [ ] **T5.6 Limit validator (pure function).** `validate_against_limits(package | ladder, redlines, bottomlines) -> list[warning]` emitting `violates_redline`, `crosses_bottomline`, `unconditional_concession`.
  *Tests:* SPEC §14.1 item 24, plus a table-driven test over boundary values. No AI call in this function.

- [ ] **T5.7 Options & Packages UI.** Inventory filterable by type and by interest served; package builder showing live validator warnings; concession ladder editor; walk-away reminder pinned in the panel and marked private.

## M6 — Brief and human layer

- [ ] **T6.1 Brief assembly.** `brief_service.py` + `generate_brief.md` producing the 18 sections in SPEC §10.2 from confirmed data only, with generation notes listing used and excluded fields.
  *Tests:* SPEC §14.1 item 20 (redlines), plus: unconfirmed bottomlines appear only under Uncertainties.

- [ ] **T6.2 Live Card.** Compressed view per SPEC §10.1 with the size cap enforced in code.
  *Test:* SPEC §14.1 item 27.

- [ ] **T6.3 Notes and judgment.** `note_service.py`: per-section My Judgment, timestamped live notes, status, pin, autosave under `APP_DATA_DIR`, edit/delete, explicit "Promote to case".
  *Test:* SPEC §14.1 item 32 (a note never becomes a confirmed fact by itself).

- [ ] **T6.4 Stale detection + regeneration.** Changing case data or organization marks affected AI bases stale; regeneration preserves all human content.
  *Test:* SPEC §14.1 item 28.

- [ ] **T6.5 Export.** `negotiation_brief.md`, `negotiation_case.json`, optional `pipeline_trace.json`. Judgment included by default, live notes optional.
  *Test:* SPEC §14.1 item 12.

## M7 — Live workspace and language assistant

- [ ] **T7.1 ZH → EN phrasing.** `language_service.py` + `phrase_in_english.md`: ≤3 variants with back-translation, tone labels, protected terms honored.
  *Test:* SPEC §14.1 item 29.

- [ ] **T7.2 Bilingual reply.** `draft_bilingual_reply.md`: what-I-heard, points to verify, ZH + EN drafts, one targeted rewrite.
  *Test:* SPEC §14.1 item 30.

- [ ] **T7.3 Risk flags.** Implement the full flag set in SPEC §11.3, including `asserts_contested_fact_as_agreed` checked against the agreement landscape and `reveals_bottomline` checked against confirmed limits.
  *Test:* SPEC §14.1 item 31, one fixture per flag.

- [ ] **T7.4 Live workspace UI.** Two-column Page 6, sticky header with walk-away trigger reminder and confirmed red-line warning, button-triggered AI only, clearable local history, save-as-note.

## M8 — Verification

- [ ] **T8.1** Full automated suite green (SPEC §14.1, items 1–32).
- [ ] **T8.2** Fake end-to-end run over the fixture set in SPEC §14.2.
- [ ] **T8.3** Streamlit smoke test across all six pages with no key.
- [ ] **T8.4** Live smoke test per SPEC §14.3 when a key is available.
- [ ] **T8.4b** Environment reproducibility: `conda env remove -n negotiation_tool` then recreate from `environment.yml`, activate, and rerun T8.1–T8.3. Fix any dependency that only worked because it was installed ad hoc.
- [ ] **T8.5** README (conda `negotiation_tool` setup as the primary install path, env vars, run, test, data location, privacy, course policy, cost limits, known limitations) + demo script from SPEC §17, checked against the §14.4 acceptance list.

---

## Prompt-writing rules (applies to every `prompts/*.md`)

1. State the role, the exact output schema, and the epistemic rules at the top.
2. Require evidence (document id + page/paragraph + excerpt) for every non-inferred claim.
3. Require `unknown` / `null` when the materials are silent. Forbid world-knowledge completion.
4. For counterpart-facing prompts, forbid claiming knowledge of their private materials and require a verification question per item.
5. For `generate_options.md`, forbid evaluation, ranking, and rejection; require coverage of the option-type list.
6. For `build_haggle_plan.md`, require a justification standard for the anchor and a reciprocal ask for every concession.
7. For language prompts, forbid new numbers, dates, commitments, and concessions; require preservation of negations and conditionals.
8. Keep hidden reasoning out of the output; only a short user-facing rationale is stored.
