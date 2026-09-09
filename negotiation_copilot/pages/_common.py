"""Shared helpers for page modules."""

import streamlit as st

from ..fixtures import sample_case
from ..models import NegotiationCase


def get_case() -> NegotiationCase:
    """Return the working case, seeding session state with the demo fixture.

    Later milestones replace this fixture with real pipeline output written
    into `st.session_state["case"]`; page modules always read through here so
    that swap is a one-line change in this function, not in every page.
    """
    if "case" not in st.session_state:
        st.session_state["case"] = sample_case()
    return st.session_state["case"]


def reviewed_text(value) -> str:
    """Render a ReviewedText (or None) as a display string with its status."""
    if value is None:
        return "_Unknown_"
    label = value.current_value or "_Unknown_"
    if value.evidence_status != "explicit":
        return f"{label}  `{value.evidence_status}`"
    return label
