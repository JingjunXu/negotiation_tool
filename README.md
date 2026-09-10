# Negotiation Copilot

A local Streamlit tool that ingests negotiation simulation materials (PDF,
DOCX, TXT, Markdown, or pasted text), reads them reliably with page-level
evidence, decides how the materials relate to each other, extracts a
machine-readable case, runs a negotiation analysis layer (interests →
agreement landscape → walk-away → constraints → options → packages),
and produces a **Living Negotiation Brief** you can annotate before and
during a live negotiation, plus a bilingual (ZH↔EN) language assistant.

Full design detail lives in [`doc/SPEC.md`](doc/SPEC.md); the build log and
design decisions are in [`doc/DECISIONS.md`](doc/DECISIONS.md); the task
queue is [`doc/TASKS.md`](doc/TASKS.md).

## Install (conda `negotiation_tool` — the only supported environment)

This project runs in one dedicated conda environment named
`negotiation_tool`. Never install into `base`, never install into the
system Python, and never create a second environment under another name.

```bash
conda env create -f environment.yml      # creates negotiation_tool with Python 3.11
conda activate negotiation_tool
pip install -r requirements.txt          # application libraries
cp .env.example .env                     # then fill OPENAI_API_KEY if you have one
```

Every session, before anything else:

```bash
conda activate negotiation_tool
python -c "import sys; print(sys.executable)"   # must contain /envs/negotiation_tool/
```

If a command fails with a missing module, check the active environment
first (`conda activate negotiation_tool`) before installing anything —
`config.py` also logs a warning at startup if `sys.prefix` doesn't look
right, so a wrong-environment run is visible immediately.

After changing dependencies:

```bash
conda env update -f environment.yml --prune
```

Teardown:

```bash
conda env remove -n negotiation_tool
```

**Dependency split:** `environment.yml` pins the Python version (3.11);
`requirements.txt` holds every application library (Streamlit, the OpenAI
SDK, Pydantic, pypdf, PyMuPDF, python-docx, python-dotenv, pytest), so a
plain venv still works if conda is unavailable. Each dependency lives in
exactly one of the two files.

## Running it

```bash
conda activate negotiation_tool
streamlit run app.py       # starts in fake/demo mode with no key configured
```

The app works fully offline without an API key — every AI-backed stage has
a deterministic, honest `FakeAIClient` fallback (see "Fake mode" below).
With a key configured in `.env`, the app automatically uses the real
`OpenAIClient` instead; no code change or flag is needed.

**No working OpenAI key? Optional alternative: the local `claude` CLI.**
This is *not* part of the project's fixed stack (see doc/DECISIONS.md) —
it's an opt-in fallback for local use if you have the Claude Code CLI
installed and logged in, but no OpenAI/Anthropic API key. Set in `.env`:

```bash
AI_PROVIDER=claude_cli
CLAUDE_CLI_MODEL=claude-sonnet-5   # optional; omit to use claude's own default
```

This shells out to `claude --print` per AI call, authenticating however
`claude` itself is already logged in — no separate API key. It only works
on a machine with `claude` installed and logged in, and spends that
login's own usage, not a separate bill. One limitation: AI-assisted PDF
reading (the fallback for pages native extraction can't read) is not
implemented under this backend and honestly reports those pages as
`needs_review` rather than fabricating a reading — see doc/DECISIONS.md
for why. Leave `AI_PROVIDER` unset to keep the original OpenAI-or-fake
behavior exactly as before.

## Testing

```bash
conda activate negotiation_tool
pytest                          # unit tests + fake end-to-end run, no network
pytest -m live                  # only if RUN_LIVE_OPENAI_TESTS=true and a key is set
```

Tests never depend on a live API key or a chat session — fixtures are
checked-in files, and the fake-mode pipeline is exercised end-to-end in
`tests/test_end_to_end.py`.

## Environment variables

Set in `.env` (never committed — see `.gitignore`):

| Variable | Default | Meaning |
| --- | --- | --- |
| `OPENAI_API_KEY` | _(empty)_ | If unset, the app runs in fake mode. |
| `OPENAI_MODEL` | _(empty)_ | Required to use `OpenAIClient`; never hardcoded in code. |
| `OPENAI_STORE_RESPONSES` | `false` | Sets `store=False` on every Responses API call unless `true`. |
| `RUN_LIVE_OPENAI_TESTS` | `false` | Gate for `pytest -m live`. |
| `APP_DATA_DIR` | `./data` | All local persistence (notes, caches) lives under here — never browser storage. |
| `MAX_UPLOAD_MB` | `25` | Per-file and running-total upload size cap. |
| `MAX_PDF_PAGES` | `50` | Per-document page cap. |
| `LOG_LEVEL` | `INFO` | Standard Python logging level. |
| `AI_PROVIDER` | _(unset = auto)_ | Not part of the fixed stack. `claude_cli` opts into the local-CLI fallback above; `fake` forces fake mode even with a key set. Unset preserves the original OpenAI-or-fake behavior. |
| `CLAUDE_CLI_PATH` | _(auto-detected)_ | Only used when `AI_PROVIDER=claude_cli`. Overrides the auto-detected `claude` executable path. |
| `CLAUDE_CLI_MODEL` | _(claude's own default)_ | Only used when `AI_PROVIDER=claude_cli`. |
| `CLAUDE_CLI_TIMEOUT_S` | `300` | Only used when `AI_PROVIDER=claude_cli`. Per-call subprocess timeout; a document that exceeds it is not lost — see "Fake mode" note below on graceful degradation. |
| `INGESTION_MAX_CONCURRENCY` | `5` | How many documents' AI extraction calls the Materials page runs at once. Real per-document AI calls are the dominant cost of uploading many files; this is what makes a multi-file batch take roughly `(file count / this number)` calls' worth of time instead of `file count` calls' worth. |

## Data location and privacy

- Everything the app writes locally lives under `APP_DATA_DIR` (`./data` by
  default) — content-addressed parse/read caches, and per-section note
  autosaves under `data/cases/<case_id>/brief_sections/`. Nothing is ever
  written to browser storage.
- Materials are tagged with a scope — `my_confidential`, `shared`, or
  `instructor_rules`. There is no counterpart-confidential scope. Counterpart
  interest hypotheses and the language assistant's context are built only
  from `shared`/`instructor_rules` content; `my_confidential` material is
  excluded from those code paths, not just prompted against.
- BATNA, reservation value, bottomline thresholds, and redline rationale are
  never included in any generated English/Chinese draft, and every draft is
  checked by deterministic code (not just the model) before being shown —
  see `negotiation_copilot/language_service.py`.
- Logs never contain API keys, full prompts, full documents, or images.
  Exports (`negotiation_brief.md`, `negotiation_case.json`,
  `pipeline_trace.json`) contain no API key and no unnecessary full text —
  see `tests/test_export.py`.
- Nothing is ever sent automatically. Every AI call is triggered by an
  explicit button click; every language-assistant draft is a local preview
  the user edits and copies themselves.

## Course policy note

This tool is built for a course negotiation simulation. It only processes
materials you upload or paste — no scraping, no external lookups, no
automatic sharing with the counterpart or instructor. Treat exported files
the same way you'd treat your own prep notes under your course's
collaboration policy.

## Cost limits

With a real API key configured, every AI-backed stage makes exactly one
(or, for PDF reading, at most two — direct file input, then a page-image
fallback only if the API rejects the file input) `responses.parse` call.
`MAX_UPLOAD_MB` and `MAX_PDF_PAGES` bound how much material reaches the
model per call. There is no automatic retry storm: `pdf_service.read_pdf`
retries a failed batch a bounded number of times before degrading to
per-page calls, and gives up per page rather than looping. Nothing runs on
a timer or in the background — cost is bounded by how many buttons you
click.

## Known limitations

- **Fake mode is honest, not a full simulation.** Every `FakeAIClient`
  method that would require real language understanding to answer safely
  (objective/BATNA/interests semantics, translation, package value
  judgments) returns an honest "not established" / empty result rather
  than a plausible-looking guess — see `doc/DECISIONS.md` for the specific
  reasoning per stage. Demoing the full richness of the analysis layer
  requires a real `OPENAI_API_KEY`.
- **`OpenAIClient` is unverified against the live API** in this build
  environment (no key was available during development) — the request/
  response shapes match the `openai` Python SDK as installed
  (`requirements.txt`), and are unit-tested with a mocked client, but a
  live smoke test (SPEC §14.3) should be run before relying on it.
- No cross-session case resume yet — a browser refresh keeps state within
  the same Streamlit session but starting a fresh session starts a fresh
  demo case. Per-section notes autosave to disk (`APP_DATA_DIR`) but
  nothing currently reads that on start-up.
- The "sticky" header on the Live Workspace page is a normal top-of-page
  block, not real scroll-sticky CSS positioning (Streamlit's layout API has
  no supported primitive for it).
- No PDF rotation/table-reconstruction beyond what native `pypdf`
  extraction and the AI vision fallback provide (see SPEC §16, P1 backlog).

## Demo script

A worked run using the real `0902files/` simulation materials as the
uploaded set:

1. Upload two or three PDFs from `0902files/` (mixed roles: a role brief,
   a news article, a meeting summary work well) and set a scope for each.
2. **Materials** page: confirm the documents and scopes.
3. **Pipeline & Relationships**: open a reading result; verify a date, a
   name, and a table relation if the PDF has one. Show the relationship
   mode (these materials are typically thematic/independent, not forced
   into a timeline) and the order/grouping comparison.
4. **Negotiation Map**: review the consolidated roles/issues/constraints;
   correct one field with Edit and confirm the original AI value is still
   visible; expand a conflict if one was detected.
5. **Strategy Lab → Interests**: run the analysis; show needs/fears/
   motives/values for both sides, with counterpart items marked
   "Hypothesis — verify."
6. **Strategy Lab → Agreement Landscape**: show a shared item next to a
   contested one with its verification question.
7. **Strategy Lab → Walk-Away**: run the analysis; show BATNA, reservation
   derivation, triggers, exit script (marked private).
8. **Strategy Lab → Limits**: run constraint classification; confirm one
   redline, demote a candidate to a bottomline, and show the difference.
9. **Strategy Lab → Options & Packages**: generate options (≥8, spanning
   ≥4 types); build a haggle plan; if a confirmed redline/bottomline is in
   play, show a validator warning on a package that would cross it.
10. **Brief Builder & Export**: generate the Prep Brief, switch to the Live
    Card, add a judgment note and pin a section, then regenerate the Brief
    to show the note survives; download `negotiation_brief.md` and
    `negotiation_case.json`.
11. **Live Workspace**: enter a Chinese intent and show the English
    variants with back-translation; paste a counterpart statement and show
    the bilingual reply draft with a risk flag if one fires.

**Done means the pipeline is stable, transparent, and demoable on real
Simulation 1 materials — not that the feature count is high.**
