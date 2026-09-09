"""Page 5 — Brief Builder & Export (SPEC §12)."""

import streamlit as st

from ._common import get_case


def render() -> None:
    st.title("Brief Builder & Export")
    st.caption("Prep Brief, Live Card, readiness warnings, and downloads.")

    case = get_case()

    st.info("Brief generation is not implemented yet (see docs/TASKS.md T6.1+).")

    if case.analysis is not None and case.analysis.generation_notes:
        st.subheader("Generation notes (from demo fixture)")
        for note in case.analysis.generation_notes:
            st.markdown(f"- {note}")

    st.subheader("Downloads")
    st.caption("negotiation_brief.md · negotiation_case.json · pipeline_trace.json (coming in T6.5)")
