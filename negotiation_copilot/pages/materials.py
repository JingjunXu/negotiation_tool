"""Page 1 — Materials (SPEC §12)."""

import streamlit as st

from ._common import get_case


def render() -> None:
    st.title("Materials")
    st.caption("Upload or paste negotiation materials and set a scope for each one.")

    case = get_case()

    st.info(
        "Upload and parsing are not implemented yet (see docs/TASKS.md T2.1+). "
        "This page currently shows the demo fixture case."
    )

    if not case.documents:
        st.write("No materials yet.")
        return

    st.subheader(f"{len(case.documents)} material(s)")
    for doc in case.documents:
        with st.expander(f"{doc.filename}  ·  {doc.scope}"):
            col1, col2, col3 = st.columns(3)
            col1.metric("Pages", doc.page_count or "—")
            col2.metric("Status", doc.processing_status)
            col3.metric("Type", doc.file_type)
            st.caption(f"document_id: {doc.document_id}  ·  sha256: {doc.sha256[:12]}…")
            if doc.pages_needing_review:
                st.warning(f"Pages needing review: {doc.pages_needing_review}")
            if doc.warnings:
                for warning in doc.warnings:
                    st.warning(warning)
