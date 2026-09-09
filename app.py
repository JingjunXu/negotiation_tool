"""Streamlit entry point — page routing only. No business logic here."""

import streamlit as st

from negotiation_copilot import config as config_module  # noqa: F401  (runs startup guard)
from negotiation_copilot.pages import (
    brief_builder,
    live_workspace,
    materials,
    negotiation_map,
    pipeline,
    strategy_lab,
)

st.set_page_config(page_title="Negotiation Copilot", layout="wide")

PAGES = [
    st.Page(materials.render, title="Materials", icon="📁", url_path="materials"),
    st.Page(pipeline.render, title="Pipeline & Relationships", icon="🔗", url_path="pipeline"),
    st.Page(negotiation_map.render, title="Negotiation Map", icon="🗺️", url_path="negotiation-map"),
    st.Page(strategy_lab.render, title="Strategy Lab", icon="🧭", url_path="strategy-lab"),
    st.Page(brief_builder.render, title="Brief Builder & Export", icon="📝", url_path="brief-builder"),
    st.Page(live_workspace.render, title="Live Workspace", icon="🎯", url_path="live-workspace"),
]

navigation = st.navigation(PAGES)
navigation.run()
