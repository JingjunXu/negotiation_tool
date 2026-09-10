"""Page 4 — Strategy Lab (SPEC §12), five tabs mirroring SPEC §8."""

import streamlit as st

from .. import agreement_service, constraint_service, interest_service, option_service, package_service, walkaway_service
from ..models import ConcessionStep
from ._common import get_ai_client, get_case, get_or_init_analysis, reviewed_text

_STANDING_LABEL = {"shared": "🟢 Shared", "contested": "🟠 Contested", "unverified": "⚪ Unverified"}
_REDLINE_SOURCE_TYPES = ["instructor_rules", "authority_limit", "legal_ethical", "principal_mandate"]


def _render_interests(case, analysis, ai_client) -> None:
    if st.button("Run interest analysis", key="run_interests"):
        with st.spinner("Analyzing interests..."):
            analysis.interests = interest_service.analyze_interests(case, ai_client=ai_client)
            analysis.position_links = interest_service.map_positions_to_interests(
                case, analysis.interests, ai_client=ai_client
            )
        st.rerun()

    if not analysis.interests:
        st.caption("No interests yet — click 'Run interest analysis'.")
    for party, label in (("me", "My interests"), ("counterpart", "Their interests (hypotheses)")):
        items = [i for i in analysis.interests if i.party == party]
        if not items:
            continue
        st.subheader(label)
        for item in items:
            prefix = "Hypothesis — verify in conversation: " if item.is_hypothesis else ""
            st.markdown(f"- **[{item.category}]** {prefix}{reviewed_text(item.statement)}")
            if item.verification_question:
                st.caption(f"Verify: {item.verification_question}")

    if analysis.position_links:
        st.subheader("Positions ↔ interests")
        for link in analysis.position_links:
            interest_labels = [i.statement.current_value for i in analysis.interests if i.id in link.underlying_interest_ids]
            st.markdown(f"- ({link.party}) *{reviewed_text(link.stated_position)}* → {interest_labels or 'no linked interest'}")
            if link.reframe_question:
                st.caption(f"Reframe: {link.reframe_question}")
            if link.misalignment_note:
                st.warning(link.misalignment_note)


def _render_agreement(case, analysis, ai_client) -> None:
    if st.button("Run agreement landscape analysis", key="run_agreement"):
        with st.spinner("Mapping agreement landscape..."):
            analysis.agreement_landscape = agreement_service.analyze_agreement_landscape(case, ai_client=ai_client)
        st.rerun()

    if not analysis.agreement_landscape:
        st.caption("No agreement landscape yet — click 'Run agreement landscape analysis'.")
        return

    cols = st.columns(3)
    for col, standing in zip(cols, ("shared", "contested", "unverified")):
        with col:
            st.markdown(f"**{_STANDING_LABEL[standing]}**")
            items = [a for a in analysis.agreement_landscape if a.standing == standing]
            if not items:
                st.caption("None")
            for item in items:
                st.markdown(f"- **[{item.kind}]** {item.statement}")
                if item.verification_question:
                    st.caption(f"❓ {item.verification_question}")
                if item.conflict_id:
                    st.caption(f"Linked conflict: `{item.conflict_id}`")


def _render_walk_away(case, analysis, ai_client) -> None:
    if st.button("Run walk-away analysis", key="run_walk_away"):
        with st.spinner("Analyzing walk-away position..."):
            analysis.walk_away, gap_warnings = walkaway_service.analyze_walk_away(case, ai_client=ai_client)
            case.warnings.extend(gap_warnings)
        st.rerun()

    walk_away = analysis.walk_away
    if walk_away is None:
        st.caption("No walk-away analysis yet — click 'Run walk-away analysis'.")
        return
    st.warning("Private — never disclose in a draft.")
    st.markdown(f"**BATNA:** {reviewed_text(walk_away.my_batna)}  ·  quality: `{walk_away.batna_quality}`")
    st.caption(walk_away.quality_rationale)
    st.markdown(f"**Reservation value:** {reviewed_text(walk_away.estimated_reservation_value)}")
    if walk_away.reservation_derivation:
        st.caption(walk_away.reservation_derivation)
    if walk_away.walk_away_triggers:
        st.subheader("Walk-away triggers")
        for trigger in walk_away.walk_away_triggers:
            st.markdown(f"- {trigger}")
    st.subheader("Exit script")
    st.write(walk_away.exit_script)


def _render_redline(analysis, redline) -> None:
    status = "✅ confirmed" if redline.confirmed_by_user else "⚠️ candidate — not yet confirmed"
    with st.expander(f"{reviewed_text(redline.statement)} ({status})"):
        st.caption(f"Source: `{redline.source_type}`  ·  Consequence: {redline.consequence_if_crossed}")
        cols = st.columns(3)
        if cols[0].button("Confirm", key=f"redline_{redline.id}_confirm", disabled=redline.confirmed_by_user):
            redline.confirmed_by_user = True
            st.rerun()
        if cols[1].button("Reject", key=f"redline_{redline.id}_reject"):
            analysis.redlines.remove(redline)
            st.rerun()
        demote_open = cols[2].checkbox("Demote to bottomline", key=f"redline_{redline.id}_demote_toggle")
        if demote_open:
            with st.form(key=f"redline_{redline.id}_demote_form"):
                direction = st.selectbox("Direction", ["min", "max"], key=f"redline_{redline.id}_direction")
                rationale = st.text_input("Rationale", key=f"redline_{redline.id}_rationale")
                risk = st.text_input("Risk if crossed", key=f"redline_{redline.id}_risk")
                if st.form_submit_button("Confirm demotion", key=f"redline_{redline.id}_demote_submit") and rationale and risk:
                    bottomline = constraint_service.demote_redline_to_bottomline(
                        redline, direction=direction, rationale=rationale, risk_if_crossed=risk
                    )
                    analysis.redlines.remove(redline)
                    analysis.bottomlines.append(bottomline)
                    st.rerun()


def _render_bottomline(analysis, bottomline) -> None:
    status = "✅ confirmed" if bottomline.confirmed_by_user else "⚠️ candidate — not yet confirmed"
    provisional = " · provisional (no BATNA link)" if bottomline.provisional else ""
    with st.expander(f"{reviewed_text(bottomline.threshold_value)} (`{bottomline.direction}`{provisional}) ({status})"):
        st.caption(f"Rationale: {bottomline.rationale}  ·  Risk if crossed: {bottomline.risk_if_crossed}")
        cols = st.columns(3)
        if cols[0].button("Confirm", key=f"bottomline_{bottomline.id}_confirm", disabled=bottomline.confirmed_by_user):
            bottomline.confirmed_by_user = True
            st.rerun()
        if cols[1].button("Reject", key=f"bottomline_{bottomline.id}_reject"):
            analysis.bottomlines.remove(bottomline)
            st.rerun()
        promote_open = cols[2].checkbox("Promote to redline", key=f"bottomline_{bottomline.id}_promote_toggle")
        if promote_open:
            with st.form(key=f"bottomline_{bottomline.id}_promote_form"):
                source_type = st.selectbox("Source type", _REDLINE_SOURCE_TYPES, key=f"bottomline_{bottomline.id}_source")
                consequence = st.text_input("Consequence if crossed", key=f"bottomline_{bottomline.id}_consequence")
                if st.form_submit_button("Confirm promotion", key=f"bottomline_{bottomline.id}_promote_submit") and consequence:
                    redline = constraint_service.promote_bottomline_to_redline(
                        bottomline, source_type=source_type, consequence_if_crossed=consequence
                    )
                    analysis.bottomlines.remove(bottomline)
                    analysis.redlines.append(redline)
                    st.rerun()


def _render_limits(case, analysis, ai_client) -> None:
    if st.button("Run constraint classification", key="run_constraints"):
        with st.spinner("Classifying constraints..."):
            analysis.redlines, analysis.bottomlines = constraint_service.classify_constraints(
                case, analysis.walk_away, ai_client=ai_client
            )
        st.rerun()

    st.caption("Immovable vs flexible — unconfirmed candidates never appear as hard limits in the Brief.")
    col1, col2 = st.columns(2)
    with col1:
        st.subheader("Redlines (immovable)")
        if not analysis.redlines:
            st.caption("None yet.")
        for redline in list(analysis.redlines):
            _render_redline(analysis, redline)
    with col2:
        st.subheader("Bottomlines (flexible)")
        if not analysis.bottomlines:
            st.caption("None yet.")
        for bottomline in list(analysis.bottomlines):
            _render_bottomline(analysis, bottomline)


def _render_option_inventory(case, analysis, ai_client) -> None:
    if st.button("Generate more options", key="generate_options"):
        with st.spinner("Generating options..."):
            new_options = option_service.generate_options(
                case, analysis.interests, ai_client=ai_client, existing_options=analysis.options
            )
            analysis.options.extend(new_options)
        st.rerun()

    if not analysis.options:
        st.caption("No options yet — click 'Generate more options'.")
        return

    st.subheader(f"Option inventory ({len(analysis.options)})")
    all_types = sorted({o.option_type for o in analysis.options})
    type_filter = st.multiselect("Filter by type", all_types, default=all_types, key="option_type_filter")

    interest_lookup = {i.id: (i.statement.current_value or i.id) for i in analysis.interests}
    interest_filter = st.multiselect(
        "Filter by interest served",
        sorted(interest_lookup.keys()),
        format_func=lambda iid: interest_lookup.get(iid, iid),
        key="option_interest_filter",
    )

    for option in analysis.options:
        if option.option_type not in type_filter:
            continue
        served_ids = set(option.serves_my_interest_ids) | set(option.serves_their_interest_ids)
        if interest_filter and not served_ids & set(interest_filter):
            continue
        st.markdown(f"- **[{option.option_type}]** {option.title} — {option.description} (`{option.status}`)")


def _render_concession_ladder(case, analysis, plan) -> None:
    st.subheader("Concession ladder")
    for step in list(plan.concession_ladder):
        cols = st.columns([5, 1])
        cols[0].markdown(
            f"{step.order}. `{step.from_value}` → `{step.to_value}`  ·  ask: {step.ask_in_return}  ·  "
            f"trigger: {step.trigger_condition}"
        )
        if cols[1].button("Remove", key=f"ladder_step_{step.order}_remove"):
            plan.concession_ladder.remove(step)
            st.rerun()

    for warning in package_service.validate_against_limits(plan.concession_ladder, analysis.redlines, analysis.bottomlines):
        st.error(warning)

    with st.form(key="add_ladder_step_form"):
        st.caption("Add a step")
        issue_ids = [i.id for i in case.issues]
        issue_lookup = {i.id: i.title for i in case.issues}
        issue_id = st.selectbox(
            "Issue (optional)", [None] + issue_ids, format_func=lambda iid: issue_lookup.get(iid, "—"), key="ladder_add_issue"
        )
        from_value = st.text_input("From value", key="ladder_add_from")
        to_value = st.text_input("To value", key="ladder_add_to")
        ask_in_return = st.text_input("Ask in return", key="ladder_add_ask")
        trigger_condition = st.text_input("Trigger condition", key="ladder_add_trigger")
        if st.form_submit_button("Add step", key="ladder_add_submit") and ask_in_return:
            plan.concession_ladder.append(
                ConcessionStep(
                    order=len(plan.concession_ladder) + 1, issue_id=issue_id, from_value=from_value,
                    to_value=to_value, ask_in_return=ask_in_return, trigger_condition=trigger_condition,
                )
            )
            st.rerun()


def _render_haggle_plan(case, analysis, ai_client) -> None:
    st.subheader("Haggle plan")
    if st.button("Build haggle plan", key="build_haggle_plan", disabled=not analysis.options):
        try:
            with st.spinner("Building packages and haggle plan..."):
                analysis.haggle_plan = package_service.build_haggle_plan(
                    case, analysis.options, analysis.interests, analysis.redlines, analysis.bottomlines,
                    ai_client=ai_client,
                )
            st.rerun()
        except ValueError as exc:
            st.error(str(exc))

    plan = analysis.haggle_plan
    if plan is None:
        st.caption("No haggle plan yet.")
        return

    st.markdown(f"**Anchor:** {plan.anchor}")
    st.caption(f"Justification standard: {plan.justification_standard}")

    st.subheader("Packages")
    for package in plan.packages:
        with st.expander(package.label):
            st.markdown(f"Give: {package.what_i_give}")
            st.markdown(f"Get: {package.what_i_get}")
            st.caption(package.equivalence_note)
            for warning in package_service.validate_against_limits(package, analysis.redlines, analysis.bottomlines):
                st.error(warning)

    _render_concession_ladder(case, analysis, plan)

    if plan.counter_tactics:
        st.subheader("Counter-tactics")
        for tactic in plan.counter_tactics:
            st.markdown(f"- **{tactic.tactic}:** {tactic.response_line}")


def _render_options(case, analysis, ai_client) -> None:
    walk_away = analysis.walk_away
    if walk_away is not None:
        triggers = ", ".join(walk_away.walk_away_triggers) or "none set"
        st.warning(
            f"🔒 Private — never disclose. Reservation value: {reviewed_text(walk_away.estimated_reservation_value)}  ·  "
            f"Triggers: {triggers}"
        )

    _render_option_inventory(case, analysis, ai_client)
    _render_haggle_plan(case, analysis, ai_client)


def render() -> None:
    st.title("Strategy Lab")
    case = get_case()
    analysis = get_or_init_analysis(case)
    ai_client = get_ai_client()

    tabs = st.tabs(["Interests", "Agreement Landscape", "Walk-Away", "Limits", "Options & Packages"])
    with tabs[0]:
        _render_interests(case, analysis, ai_client)
    with tabs[1]:
        _render_agreement(case, analysis, ai_client)
    with tabs[2]:
        _render_walk_away(case, analysis, ai_client)
    with tabs[3]:
        _render_limits(case, analysis, ai_client)
    with tabs[4]:
        _render_options(case, analysis, ai_client)
