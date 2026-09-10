"""Page 3 — Negotiation Map (SPEC §12): roles, context, objective, BATNA,
interests, positions, issues, constraints, deadlines, conflicts, open
questions — with an evidence viewer and Confirm/Edit/Reject on every field.
"""

import streamlit as st

from ._common import get_case, render_evidence, render_reviewed_field, reviewed_text

_SINGULAR_FIELDS = [
    ("my_role", "My role"),
    ("counterpart_role", "Counterpart role"),
    ("context", "Context"),
    ("objective", "Objective"),
    ("batna", "BATNA"),
]


def _render_singular_fields(case) -> None:
    cols = st.columns(len(_SINGULAR_FIELDS))
    for col, (field_name, label) in zip(cols, _SINGULAR_FIELDS):
        with col:
            render_reviewed_field(
                case,
                get_value=lambda c, f=field_name: getattr(c, f),
                set_value=lambda c, v, f=field_name: setattr(c, f, v),
                label=label,
                key=f"map_{field_name}",
            )


def _render_reviewed_list(title: str, items: list) -> None:
    if not items:
        return
    st.subheader(title)
    for item in items:
        st.markdown(f"- {reviewed_text(item)}")
        render_evidence(item)


def _render_issues(case) -> None:
    if not case.issues:
        return
    st.subheader("Issues (by priority)")
    priority_rank = {"high": 0, "medium": 1, "low": 2, "unknown": 3}
    ordered = sorted(case.issues, key=lambda i: priority_rank.get(i.priority, 3))
    for issue in ordered:
        with st.expander(f"{issue.title}  ·  {issue.priority} priority  ·  {issue.flexibility}  ·  `{issue.status}`"):
            st.markdown(f"My position: {reviewed_text(issue.my_position)}")
            render_evidence(issue.my_position)
            st.markdown(f"Counterpart position: {reviewed_text(issue.counterpart_position)}")
            render_evidence(issue.counterpart_position)
            render_reviewed_field(
                case,
                get_value=lambda c, iid=issue.id: next((i.target for i in c.issues if i.id == iid), None),
                set_value=lambda c, v, iid=issue.id: _set_issue_field(c, iid, "target", v),
                label="Target",
                key=f"issue_{issue.id}_target",
            )
            st.markdown(f"Acceptable range: {reviewed_text(issue.acceptable_range)}")
            render_evidence(issue.acceptable_range)
            if issue.evidence:
                with st.expander(f"Issue-level evidence ({len(issue.evidence)})"):
                    for e in issue.evidence:
                        location = f"p.{e.page_number}" if e.page_number is not None else (e.paragraph_id or "—")
                        st.markdown(f"- `{e.document_id}` ({location}): “{e.excerpt}”")


def _set_issue_field(case, issue_id: str, field: str, value) -> None:
    for issue in case.issues:
        if issue.id == issue_id:
            setattr(issue, field, value)
            return


def render() -> None:
    st.title("Negotiation Map")
    st.caption("Roles, context, objective, issues, constraints, deadlines, conflicts, and open questions.")

    case = get_case()

    _render_singular_fields(case)

    _render_reviewed_list("Interests (raw, pre-analysis)", case.interests)
    _render_reviewed_list("Positions", case.positions)
    _render_reviewed_list("Targets", case.targets)
    _render_reviewed_list("Possible concessions", case.possible_concessions)
    _render_reviewed_list("Counterpart information", case.counterpart_information)
    _render_reviewed_list("Authority limits", case.authority_limits)

    _render_issues(case)

    if case.hard_constraints:
        st.subheader("Constraints")
        for constraint in case.hard_constraints:
            st.markdown(f"- {reviewed_text(constraint.statement)}  ·  `{constraint.source_type}`")
            render_evidence(constraint.statement)

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
