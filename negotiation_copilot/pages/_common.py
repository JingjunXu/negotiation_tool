"""Shared helpers for page modules."""

from typing import Callable

import streamlit as st

from ..ai_client import AIClient, OpenAIClient
from ..claude_cli_client import ClaudeCliClient
from ..config import config
from ..fake_clients import FakeAIClient
from ..fixtures import sample_case
from ..models import NegotiationAnalysis, NegotiationCase, ReviewedText


def get_ai_client() -> AIClient:
    """The AIClient for this session, chosen by `config.effective_provider`:
    OpenAI if a key is configured (the default), the opt-in `claude_cli`
    backend if AI_PROVIDER=claude_cli is set, fake mode otherwise. Cached
    in session_state so pages share one instance."""
    if "ai_client" not in st.session_state:
        provider = config.effective_provider
        if provider == "openai":
            client: AIClient = OpenAIClient(config)
        elif provider == "claude_cli":
            client = ClaudeCliClient(config)
        else:
            client = FakeAIClient()
        st.session_state["ai_client"] = client
    return st.session_state["ai_client"]


def get_or_init_analysis(case: NegotiationCase) -> NegotiationAnalysis:
    if case.analysis is None:
        case.analysis = NegotiationAnalysis()
    return case.analysis


def get_brief():
    """The current NegotiationBrief, or None if not generated yet.

    Kept as its own session_state key (not a NegotiationCase field) since
    it's a derived artifact regenerated on demand, not extracted content.
    """
    return st.session_state.get("brief")


def set_brief(brief) -> None:
    st.session_state["brief"] = brief

STATUS_BADGES = {
    "explicit": "✅ explicit",
    "inferred": "🟡 inferred",
    "unknown": "⚪ unknown",
    "user_confirmed": "🔵 user confirmed",
}


def get_case() -> NegotiationCase:
    """Return the working case, seeding session state with the demo fixture.

    Later milestones replace this fixture with real pipeline output written
    into `st.session_state["case"]`; page modules always read through here so
    that swap is a one-line change in this function, not in every page.
    """
    if "case" not in st.session_state:
        st.session_state["case"] = sample_case()
        st.session_state["case_is_demo"] = True
    return st.session_state["case"]


def is_demo_case() -> bool:
    """True until the first real material replaces the seeded demo fixture.

    Materials page uses this to avoid mixing real uploads into the demo
    case's documents — it starts a fresh empty case instead.
    """
    return bool(st.session_state.get("case_is_demo"))


def set_case(case: NegotiationCase) -> None:
    st.session_state["case"] = case
    st.session_state["case_is_demo"] = False


def reviewed_text(value) -> str:
    """Render a ReviewedText (or None) as a display string with its status."""
    if value is None:
        return "_Unknown_"
    label = value.current_value or "_Unknown_"
    if value.evidence_status != "explicit":
        return f"{label}  `{value.evidence_status}`"
    return label


def render_evidence(value: ReviewedText | None) -> None:
    """Collapsed evidence viewer for one ReviewedText."""
    if value is None or not value.evidence:
        return
    with st.expander(f"Evidence ({len(value.evidence)})"):
        for e in value.evidence:
            location = f"p.{e.page_number}" if e.page_number is not None else (e.paragraph_id or "—")
            st.markdown(f"- `{e.document_id}` ({location}): “{e.excerpt}”")


def render_reviewed_field(
    case: NegotiationCase,
    get_value: Callable[[NegotiationCase], ReviewedText | None],
    set_value: Callable[[NegotiationCase, ReviewedText], None],
    *,
    label: str,
    key: str,
) -> None:
    """A reusable Confirm/Edit/Reject control for one ReviewedText field.

    Every mutation uses `model_copy(update=...)`, so `ai_original_value` is
    never touched — edits and rejects only ever change `current_value` and
    `evidence_status` (SPEC §14.1 item 11, "Human notes are sacred" analog
    for extracted fields). Reused by later Strategy Lab / Limits UI tasks.
    """
    value = get_value(case)
    st.markdown(f"**{label}**")
    if value is None:
        st.caption("_Unknown_")
    else:
        st.write(value.current_value or "_Unknown_")
        st.caption(STATUS_BADGES.get(value.evidence_status, value.evidence_status))
        render_evidence(value)

    cols = st.columns(3)
    if cols[0].button("Confirm", key=f"{key}_confirm", disabled=value is None):
        set_value(case, value.model_copy(update={"evidence_status": "user_confirmed"}))
        st.rerun()
    edit_open = cols[1].checkbox("Edit", key=f"{key}_edit_toggle")
    if cols[2].button("Reject", key=f"{key}_reject", disabled=value is None):
        set_value(case, value.model_copy(update={"current_value": None, "evidence_status": "unknown"}))
        st.rerun()

    if edit_open:
        default = (value.current_value if value else "") or ""
        new_value = st.text_input("New value", value=default, key=f"{key}_edit_input")
        if st.button("Save", key=f"{key}_save"):
            base = value or ReviewedText(current_value=None, ai_original_value=None, evidence_status="unknown", evidence=[])
            set_value(case, base.model_copy(update={"current_value": new_value, "evidence_status": "user_confirmed"}))
            st.rerun()
