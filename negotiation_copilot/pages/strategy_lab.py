"""Page 4 — Strategy Lab (SPEC §12), five tabs mirroring SPEC §8."""

import streamlit as st

from ._common import get_case, reviewed_text


def _render_interests(analysis) -> None:
    if not analysis.interests:
        st.write("No interests yet.")
        return
    for party, label in (("me", "My interests"), ("counterpart", "Their interests (hypotheses)")):
        st.subheader(label)
        items = [i for i in analysis.interests if i.party == party]
        if not items:
            st.caption("None yet.")
            continue
        for item in items:
            prefix = "Hypothesis — verify in conversation: " if item.is_hypothesis else ""
            st.markdown(f"- **[{item.category}]** {prefix}{reviewed_text(item.statement)}")
            if item.verification_question:
                st.caption(f"Verify: {item.verification_question}")

    if analysis.position_links:
        st.subheader("Positions ↔ interests")
        for link in analysis.position_links:
            st.markdown(f"- ({link.party}) *{reviewed_text(link.stated_position)}* → interests: {link.underlying_interest_ids}")
            if link.reframe_question:
                st.caption(f"Reframe: {link.reframe_question}")


def _render_agreement(analysis) -> None:
    if not analysis.agreement_landscape:
        st.write("No agreement landscape yet.")
        return
    for standing in ("shared", "contested", "unverified"):
        items = [a for a in analysis.agreement_landscape if a.standing == standing]
        if not items:
            continue
        st.subheader(standing.capitalize())
        for item in items:
            st.markdown(f"- **[{item.kind}]** {item.statement}")
            if item.verification_question:
                st.caption(f"Verify: {item.verification_question}")


def _render_walk_away(analysis) -> None:
    walk_away = analysis.walk_away
    if walk_away is None:
        st.write("No walk-away analysis yet.")
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


def _render_limits(analysis) -> None:
    col1, col2 = st.columns(2)
    with col1:
        st.subheader("Redlines (immovable)")
        for redline in analysis.redlines:
            status = "✅ confirmed" if redline.confirmed_by_user else "⚠️ candidate — not yet confirmed"
            st.markdown(f"- {reviewed_text(redline.statement)} ({status})")
    with col2:
        st.subheader("Bottomlines (flexible)")
        for bottomline in analysis.bottomlines:
            provisional = " · provisional" if bottomline.provisional else ""
            st.markdown(f"- {reviewed_text(bottomline.threshold_value)} (`{bottomline.direction}`{provisional})")


def _render_options(analysis) -> None:
    if analysis.options:
        st.subheader(f"Option inventory ({len(analysis.options)})")
        for option in analysis.options:
            st.markdown(f"- **[{option.option_type}]** {option.title} — {option.description} (`{option.status}`)")

    plan = analysis.haggle_plan
    if plan is not None:
        st.subheader("Haggle plan")
        st.markdown(f"**Anchor:** {plan.anchor}")
        st.caption(f"Justification standard: {plan.justification_standard}")
        for package in plan.packages:
            st.markdown(f"- **{package.label}** — give: {package.what_i_give}; get: {package.what_i_get}")
            if package.validator_warnings:
                for warning in package.validator_warnings:
                    st.error(warning)


def render() -> None:
    st.title("Strategy Lab")
    case = get_case()
    analysis = case.analysis

    if analysis is None:
        st.info("No analysis yet. This runs after consolidation (see docs/TASKS.md M4-M5).")
        return

    tabs = st.tabs(["Interests", "Agreement Landscape", "Walk-Away", "Limits", "Options & Packages"])
    with tabs[0]:
        _render_interests(analysis)
    with tabs[1]:
        _render_agreement(analysis)
    with tabs[2]:
        _render_walk_away(analysis)
    with tabs[3]:
        _render_limits(analysis)
    with tabs[4]:
        _render_options(analysis)
