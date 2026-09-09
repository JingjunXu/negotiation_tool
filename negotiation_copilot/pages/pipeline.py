"""Page 2 — Pipeline & Relationships (SPEC §12)."""

import streamlit as st

from ._common import get_case


def render() -> None:
    st.title("Pipeline & Relationships")
    st.caption("Per-page reading status, relationship judgment, and structured intermediates.")

    case = get_case()
    org = case.organization

    st.info(
        "PDF reading and relationship classification are not implemented yet "
        "(see docs/TASKS.md T2.2+ and T3.1+). Showing the demo fixture's organization result."
    )

    if org is None:
        st.write("No organization result yet.")
        return

    st.subheader("Relationship mode")
    st.write(f"**{org.organization_mode}**  ·  temporal order applicable: {org.temporal_order_applicable}")
    st.caption(f"Review status: {org.review_status}")

    if org.groups:
        st.subheader("Groups")
        for group in org.groups:
            st.markdown(f"- **{group.name}** — {group.organizing_reason} ({len(group.document_ids)} document(s))")

    if org.relations:
        st.subheader("Pairwise relations")
        for rel in org.relations:
            st.markdown(
                f"- `{rel.source_document_id}` → **{rel.relation_type}** "
                f"({rel.confidence} confidence): {rel.explanation}"
            )

    if org.unresolved_ambiguities:
        st.subheader("Unresolved ambiguities")
        for item in org.unresolved_ambiguities:
            st.warning(item)

    with st.expander("Raw organization JSON"):
        st.json(org.model_dump(mode="json"))
