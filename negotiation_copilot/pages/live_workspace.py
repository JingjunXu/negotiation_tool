"""Page 6 — Live Negotiation Workspace (SPEC §12)."""

import streamlit as st

from ._common import get_case


def render() -> None:
    st.title("Live Negotiation Workspace")

    case = get_case()
    walk_away = case.analysis.walk_away if case.analysis else None
    if walk_away is not None and walk_away.walk_away_triggers:
        st.warning("Walk-away trigger reminder: " + "; ".join(walk_away.walk_away_triggers))

    left, right = st.columns(2)
    with left:
        st.subheader("Living Brief")
        st.info("Live Card and notes are not implemented yet (see docs/TASKS.md T6.2-T6.3).")
    with right:
        st.subheader("Language Assistant")
        st.info("ZH↔EN phrasing and bilingual reply drafting are not implemented yet (see docs/TASKS.md T7.1-T7.3).")
