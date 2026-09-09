"""Page 3 — Negotiation Map (SPEC §12)."""

import streamlit as st

from ._common import get_case, reviewed_text


def render() -> None:
    st.title("Negotiation Map")
    st.caption("Roles, context, objective, issues, constraints, deadlines, conflicts, and open questions.")

    case = get_case()

    col1, col2 = st.columns(2)
    col1.markdown(f"**My role:** {reviewed_text(case.my_role)}")
    col2.markdown(f"**Counterpart role:** {reviewed_text(case.counterpart_role)}")
    st.markdown(f"**Context:** {reviewed_text(case.context)}")
    st.markdown(f"**Objective:** {reviewed_text(case.objective)}")
    st.markdown(f"**BATNA:** {reviewed_text(case.batna)}")

    if case.issues:
        st.subheader("Issues")
        st.dataframe(
            [
                {
                    "Title": issue.title,
                    "My position": reviewed_text(issue.my_position),
                    "Target": reviewed_text(issue.target),
                    "Priority": issue.priority,
                    "Flexibility": issue.flexibility,
                    "Status": issue.status,
                }
                for issue in case.issues
            ],
            width="stretch",
        )

    if case.hard_constraints:
        st.subheader("Constraints")
        for constraint in case.hard_constraints:
            st.markdown(f"- {reviewed_text(constraint.statement)}  ·  `{constraint.source_type}`")

    if case.deadlines:
        st.subheader("Deadlines")
        for deadline in case.deadlines:
            st.markdown(f"- {deadline.description}: {deadline.date_text or 'unknown date'}")

    if case.conflicts:
        st.subheader("Conflicts")
        for conflict in case.conflicts:
            values = ", ".join(f"{v.document_id}: {v.value}" for v in conflict.values)
            st.warning(f"{conflict.field_description} — {values} (`{conflict.resolution_status}`)")

    if case.open_questions:
        st.subheader("Open questions")
        for question in case.open_questions:
            st.markdown(f"- {question.question}")

    if case.warnings:
        st.subheader("Warnings")
        for warning in case.warnings:
            st.warning(warning)
