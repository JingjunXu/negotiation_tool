"""Page 6 — Live Negotiation Workspace (SPEC §12). Two columns: Living
Brief / Live Card on the left, language assistant on the right. Every AI
call is button-triggered; nothing here ever sends anything anywhere.
"""

from datetime import datetime, timezone

import streamlit as st

from .. import language_service, note_service
from ..models import LanguageDraftRequest, LiveInteraction
from ._common import get_ai_client, get_brief, get_case

_TONES = ["collaborative", "neutral", "firm"]
_STATUS_OPTIONS = ["confirmed", "tentative", "needs_verification", "no_longer_relevant"]


def _render_header(analysis) -> None:
    walk_away = analysis.walk_away if analysis else None
    confirmed_redlines = [r for r in (analysis.redlines if analysis else []) if r.confirmed_by_user]

    cols = st.columns(2)
    with cols[0]:
        if walk_away and walk_away.walk_away_triggers:
            st.warning("🔒 Walk-away triggers: " + "; ".join(walk_away.walk_away_triggers))
        else:
            st.caption("No walk-away triggers established yet.")
    with cols[1]:
        if confirmed_redlines:
            names = "; ".join(r.statement.current_value for r in confirmed_redlines if r.statement.current_value)
            st.error(f"🚫 Confirmed redlines: {names}")
        else:
            st.caption("No confirmed redlines yet.")


def _render_living_brief(case, brief) -> None:
    st.subheader("Living Brief")
    if brief is None:
        st.caption("No brief yet — generate one on the Brief Builder page.")
        return

    pinned_only = st.checkbox("Pinned only", key="live_pinned_only")
    status_filter = st.multiselect("Filter by status", _STATUS_OPTIONS, key="live_status_filter")

    for section in brief.sections:
        if pinned_only and not section.pinned:
            continue
        if status_filter and section.status not in status_filter:
            continue
        with st.expander(section.title):
            st.markdown(section.ai_generated_base)
            note_text = st.text_area("Add a timestamped live note", key=f"live_note_{section.section_id}")
            if st.button("Save note", key=f"live_note_{section.section_id}_save") and note_text:
                note_service.add_note(case.case_id, section, "live_note", note_text)
                st.rerun()


def _save_as_note(case, brief, text: str, key_prefix: str) -> None:
    if brief is None:
        st.caption("Generate a Brief first to save drafts as notes.")
        return
    section_ids = [s.section_id for s in brief.sections]
    titles = {s.section_id: s.title for s in brief.sections}
    target_id = st.selectbox(
        "Save as a live note under", section_ids, format_func=lambda sid: titles.get(sid, sid), key=f"{key_prefix}_target_section"
    )
    if st.button("Save as note", key=f"{key_prefix}_save_note"):
        section = next(s for s in brief.sections if s.section_id == target_id)
        note_service.add_note(case.case_id, section, "live_note", text)
        st.success(f"Saved to '{section.title}'.")


def _render_variant(case, brief, variant, key_prefix: str) -> None:
    st.markdown(f"**{variant.label}**")
    st.write(variant.english_draft)
    st.caption(f"Back-translation: {variant.chinese_back_translation}")
    if variant.risk_flags:
        st.error("Risk flags: " + ", ".join(variant.risk_flags))
    _save_as_note(case, brief, variant.english_draft, key_prefix)


def _append_history(mode: str, user_input: str, output: dict) -> None:
    history = st.session_state.setdefault("live_history", [])
    history.append(
        LiveInteraction(created_at=datetime.now(timezone.utc), mode=mode, user_input=user_input, output=output)
    )


def _render_mode_a(case, brief, ai_client) -> None:
    st.subheader("Chinese intent → English")
    text = st.text_area("Your intent (any language)", key="mode_a_input")
    tone = st.selectbox("Tone", _TONES, key="mode_a_tone")
    if st.button("Generate phrasing", key="mode_a_generate") and text:
        request = LanguageDraftRequest(mode="chinese_to_english", user_input=text, input_language="auto", tone=tone)
        with st.spinner("Phrasing..."):
            variants = language_service.phrase_in_english(request, case, ai_client=ai_client, brief=brief)
        st.session_state["mode_a_variants"] = variants
        _append_history("chinese_to_english", text, {"variants": [v.model_dump(mode="json") for v in variants]})

    for i, variant in enumerate(st.session_state.get("mode_a_variants", [])):
        _render_variant(case, brief, variant, f"mode_a_{i}")


def _render_mode_b(case, brief, ai_client) -> None:
    st.subheader("Counterpart statement → bilingual reply")
    text = st.text_area("Paste what they said", key="mode_b_input")
    tone = st.selectbox("Tone", _TONES, key="mode_b_tone")
    if st.button("Draft reply", key="mode_b_generate") and text:
        request = LanguageDraftRequest(mode="reply_to_counterpart", user_input=text, input_language="auto", tone=tone)
        with st.spinner("Drafting..."):
            draft = language_service.draft_bilingual_reply(request, case, ai_client=ai_client, brief=brief)
        st.session_state["mode_b_draft"] = draft
        _append_history("reply_to_counterpart", text, draft.model_dump(mode="json"))

    draft = st.session_state.get("mode_b_draft")
    if draft is not None:
        st.markdown(f"**What I heard:** {draft.counterpart_summary_en or draft.counterpart_summary_zh or 'n/a'}")
        if draft.points_to_verify:
            st.markdown("**Points to verify:** " + "; ".join(draft.points_to_verify))
        st.markdown("**Chinese draft:**")
        st.write(draft.chinese_draft)
        st.markdown("**English draft:**")
        st.write(draft.english_draft)
        if draft.risk_flags:
            st.error("Risk flags: " + ", ".join(draft.risk_flags))
        _save_as_note(case, brief, draft.english_draft, "mode_b")


def _render_history() -> None:
    history = st.session_state.get("live_history", [])
    if not history:
        return
    with st.expander(f"Recent history ({len(history)})"):
        for entry in reversed(history[-10:]):
            st.caption(f"[{entry.mode}] {entry.user_input[:80]}")
    if st.button("Clear history", key="clear_live_history"):
        st.session_state["live_history"] = []
        st.rerun()


def render() -> None:
    st.title("Live Negotiation Workspace")
    case = get_case()
    analysis = case.analysis
    brief = get_brief()
    ai_client = get_ai_client()

    _render_header(analysis)

    left, right = st.columns(2)
    with left:
        _render_living_brief(case, brief)
    with right:
        tab_a, tab_b = st.tabs(["ZH → EN", "Reply to counterpart"])
        with tab_a:
            _render_mode_a(case, brief, ai_client)
        with tab_b:
            _render_mode_b(case, brief, ai_client)
        _render_history()
