# CLAUDE.md — Negotiation Copilot

Always-loaded operating rules for this repository. Keep this file short. Details live in `docs/SPEC.md`; the work queue lives in `docs/TASKS.md`.

## What we are building

A local Streamlit tool that ingests real negotiation simulation materials (PDF/DOCX/TXT/MD/pasted text), reads them reliably, decides how the materials relate to each other, extracts a machine-readable case, runs a **negotiation analysis layer** (interests → agreement landscape → walk-away → constraints → options → packages), and produces a **Living Negotiation Brief** the user can annotate before and during a live negotiation, plus a bilingual (ZH↔EN) language assistant.

First release = one stable, transparent, locally demoable loop. Do not add features outside P0.

## Working agreement

1. Work **one task at a time** from `docs/TASKS.md`, in order. Before starting a task, read the SPEC sections it references.
2. After every task: the app must still start (`streamlit run app.py`) and `pytest` must pass.
3. Write the test in the same task as the feature. No task is done without its acceptance test.
4. Prefer small, reviewable diffs. Do not refactor unrelated modules opportunistically.
5. If the SPEC is ambiguous, pick the option that keeps evidence traceable and human judgment authoritative, then record the decision in `docs/DECISIONS.md`.
6. Never invent negotiation content that is not in the materials or written by the user.

## Stack (fixed)

Python 3.11+ · Streamlit · OpenAI Python SDK (Responses API) · Pydantic v2 · pypdf (native text check) · PyMuPDF (page rendering, adapter-internal only) · python-docx · python-dotenv · pytest

## Environment — conda, name `negotiation_tool`

This project runs in a dedicated conda environment called **`negotiation_tool`**. Never install into `base`, never install into the system Python, and never assume the environment is already active.

First-time setup:

```bash
conda env create -f environment.yml      # creates negotiation_tool with Python 3.11
conda activate negotiation_tool
pip install -r requirements.txt          # pip-only deps, see §Dependency split
cp .env.example .env                     # then fill OPENAI_API_KEY if available
```

Every session, before anything else:

```bash
conda activate negotiation_tool
python -c "import sys; print(sys.executable)"   # must contain /envs/negotiation_tool/
```

After changing dependencies:

```bash
conda env update -f environment.yml --prune
```

**Dependency split:** `environment.yml` pins the Python version and anything that benefits from conda-forge binaries (python, pip, pytest). Application libraries stay in `requirements.txt` so a plain venv still works. Keep the two files consistent — a dependency belongs in exactly one of them.

`environment.yml` must look like this:

```yaml
name: negotiation_tool
channels:
  - conda-forge
dependencies:
  - python=3.11
  - pip
  - pip:
      - -r requirements.txt
```

## Commands

Run all of these with `negotiation_tool` active.

```bash
streamlit run app.py                 # app, works with no API key (fake mode)
pytest                               # unit + fake end-to-end
pytest -m live                       # only when RUN_LIVE_OPENAI_TESTS=true and key is set
```

If a command fails with a missing module, check the active environment first before installing anything — the usual cause is a shell that never ran `conda activate negotiation_tool`.

## Repo map

```
environment.yml                conda env definition (name: negotiation_tool)
requirements.txt               application dependencies (pip)
app.py                         Streamlit entry, page routing only
negotiation_copilot/
  config.py models.py storage.py
  document_parser.py pdf_ingestion.py pdf_service.py
  material_organization_service.py extraction_service.py consolidation_service.py
  interest_service.py            # needs / fears / motives / values, positions vs interests
  agreement_service.py           # islands of agreement
  walkaway_service.py            # BATNA, reservation value, walk-away triggers
  constraint_service.py          # redlines vs bottomlines
  option_service.py              # expand the pie
  package_service.py             # MESOs + concession ladder + counter-tactics
  brief_service.py note_service.py language_service.py
  ai_client.py fake_clients.py
prompts/                        one .md per AI call, no prompts inline in UI code
tests/                          fixtures/ + one test module per service
docs/SPEC.md docs/TASKS.md docs/DECISIONS.md
data/                           runtime artifacts, gitignored
```

## Domain vocabulary (do not conflate these)

| Term | Meaning in this codebase |
| --- | --- |
| **Position** | What a party says they want ("$120k, 30 days"). Surface-level, negotiable. |
| **Interest** | Why they want it. Split into **needs / fears / motives / values**. |
| **Island of agreement** | A fact, value, or process point both sides already accept. Contested items are tracked separately, never merged into islands. |
| **Redline** | Immovable. Sourced from instructor rules, authority limits, legal/ethical bounds, or a principal's mandate. Crossing it means no deal. Binary. Requires explicit user confirmation. |
| **Bottomline** | Flexible threshold where risk starts to outweigh benefit. Has a value/range, a rationale, and revisit conditions. Derived from BATNA, never from aspiration. |
| **Target** | What we aim for. Ambitious, not a constraint. |
| **Option** | An invented possibility, not yet evaluated or offered. |
| **Package / MESO** | Multiple equivalent simultaneous offers built from options. |
| **Walk-away** | The decision to take the BATNA. Always modeled, always visible to the user, never disclosed in any draft. |

## Non-negotiable invariants

- **Evidence or nothing.** Every extracted claim carries `document_id`, page/paragraph, and a short excerpt. Missing data is `null` / `unknown`, never filled in from world knowledge.
- **Label epistemic status** everywhere: `explicit | inferred | unknown | user_confirmed`. Never render `inferred` as fact.
- **AI cannot create a redline.** `Redline.confirmed_by_user` must be `True` before it appears in the Brief's Redlines section. Unconfirmed candidates go to Uncertainties.
- **Bottomline requires a BATNA link.** No BATNA → bottomline is `provisional` and flagged as a preparation gap.
- **Counterpart interests are hypotheses.** Every counterpart needs/fears/motives/values item renders with `Hypothesis — verify in conversation` and carries a verification question.
- **Invention ≠ decision.** The option generation stage must not filter for feasibility or evaluate value. Only the user, or the redline validator, may reject an option.
- **No forced chronology.** Do not order materials unless textual evidence supports it. Filenames never override body text.
- **Human notes are sacred.** Regenerating any AI output must never overwrite `My Judgment` or `Live Notes`. Mark stale AI bases as stale instead.
- **Never auto-send.** Every AI call is button-triggered. Drafts land in a preview the user edits and copies.
- **Never disclose** BATNA, reservation value, bottomline, or redline rationale in any generated English/Chinese draft. Risk-flag drafts that would.
- **Only permitted materials.** Scopes are `my_confidential | shared | instructor_rules`. There is no counterpart-confidential scope.
- **Secrets.** API key from environment only. Never log keys, full prompts, full documents, or images. Exports contain no keys.

## Never do

- Do not hardcode a model name; read `OPENAI_MODEL`.
- Do not build prompts inside Streamlit page code.
- Do not use browser storage; persist under `APP_DATA_DIR`.
- Do not make tests depend on network or on a chat session; fixtures are checked-in files.
- Do not install packages into `base` or the system Python, and do not create a second env under another name; the only environment is `negotiation_tool`.
- Do not commit the env directory, `.env`, or `conda-meta`; `environment.yml` is the source of truth.
- Do not add utility scores, ZOPA math, acceptance probabilities, or simulated opponents in P0 (see SPEC §16).
