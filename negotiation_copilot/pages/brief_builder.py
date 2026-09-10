"""Page 5 — Brief Builder & Export (SPEC §12)."""

import streamlit as st

from .. import brief_service, note_service
from ._common import get_ai_client, get_brief, get_case, set_brief

_STATUS_OPTIONS = ["confirmed", "tentative", "needs_verification", "no_longer_relevant"]
_PROMOTION_TARGETS = ["redline_candidate", "bottomline_candidate", "open_question", "agreement_item"]


def _render_notes(case, section) -> None:
    st.markdown("**My Judgment & Live Notes**")
    for note in list(section.notes):
        cols = st.columns([5, 1, 1])
        cols[0].markdown(f"_{note.note_type}_ ({note.updated_at:%Y-%m-%d %H:%M}): {note.text}")
        if cols[1].button("Delete", key=f"note_{note.id}_delete"):
            note_service.delete_note(case.case_id, section, note.id)
            st.rerun()
        promote_open = cols[2].checkbox("Promote", key=f"note_{note.id}_promote_toggle")
        if promote_open:
            with st.form(key=f"note_{note.id}_promote_form"):
                target = st.selectbox("Promote to case as", _PROMOTION_TARGETS, key=f"note_{note.id}_target")
                if st.form_submit_button("Confirm promotion", key=f"note_{note.id}_promote_submit"):
                    note_service.promote_note_to_case(case, note, target)
                    st.success(f"Promoted as a {target.replace('_', ' ')} (still requires its own confirmation).")
                    st.rerun()

    with st.form(key=f"section_{section.section_id}_add_note_form"):
        note_type = st.radio(
            "Type", ["my_judgment", "live_note"], key=f"section_{section.section_id}_note_type", horizontal=True
        )
        text = st.text_area("New note", key=f"section_{section.section_id}_note_text")
        if st.form_submit_button("Add note", key=f"section_{section.section_id}_add_note_submit") and text:
            note_service.add_note(case.case_id, section, note_type, text)
            st.rerun()


def _render_section(case, section) -> None:
    flags = (" 🔶 stale" if section.stale else "") + (" 📌" if section.pinned else "")
    with st.expander(f"{section.title}{flags}  ·  `{section.status}`"):
        st.markdown(section.ai_generated_base)

        cols = st.columns(2)
        new_status = cols[0].selectbox(
            "Status", _STATUS_OPTIONS, index=_STATUS_OPTIONS.index(section.status), key=f"section_{section.section_id}_status"
        )
        if new_status != section.status:
            note_service.set_status(case.case_id, section, new_status)
            st.rerun()
        pin_value = cols[1].checkbox("Pinned", value=section.pinned, key=f"section_{section.section_id}_pin")
        if pin_value != section.pinned:
            note_service.set_pinned(case.case_id, section, pin_value)
            st.rerun()

        if section.evidence:
            with st.expander(f"Evidence ({len(section.evidence)})"):
                for e in section.evidence:
                    location = f"p.{e.page_number}" if e.page_number is not None else (e.paragraph_id or "—")
                    st.markdown(f"- `{e.document_id}` ({location}): “{e.excerpt}”")

        _render_notes(case, section)


def _render_live_card(case, brief) -> None:
    card = brief_service.build_live_card(case, brief)
    st.markdown(f"**Walk-away:** {card.walk_away_line}")
    st.markdown("**Redlines:** " + ("; ".join(card.redlines) or "None confirmed"))
    st.markdown("**My top interests:** " + ("; ".join(card.my_top_interests) or "None"))
    st.markdown("**Their top interests (hypotheses):** " + ("; ".join(card.their_top_interests) or "None"))
    st.markdown("**Shared-facts opener:** " + ("; ".join(card.shared_facts_opener) or "None"))
    st.markdown("**Packages:** " + ("; ".join(card.packages) or "None"))
    st.markdown("**Next questions:** " + ("; ".join(card.next_questions) or "None"))
    if card.pinned_sections:
        st.subheader("Pinned sections")
        for section in card.pinned_sections:
            st.markdown(f"**{section.title}**: {section.ai_generated_base}")


def render() -> None:
    st.title("Brief Builder & Export")
    case = get_case()
    ai_client = get_ai_client()
    brief = get_brief()

    if st.button("Generate Prep Brief", key="generate_brief"):
        with st.spinner("Assembling the brief..."):
            new_brief = brief_service.generate_brief(case, ai_client=ai_client)
            if brief is not None:
                # Regenerating the Brief preserves all human content (SPEC §10.4);
                # full stale-marking on top of this lives in T6.4.
                previous_by_id = {s.section_id: s for s in brief.sections}
                for section in new_brief.sections:
                    previous = previous_by_id.get(section.section_id)
                    if previous is not None:
                        section.notes = previous.notes
                        section.status = previous.status
                        section.pinned = previous.pinned
            set_brief(new_brief)
        st.rerun()

    if brief is None:
        st.info("No brief yet. Click 'Generate Prep Brief'.")
        return

    brief_service.refresh_staleness(case, brief)

    if brief.generation_notes:
        st.subheader("Generation notes")
        for note in brief.generation_notes:
            st.caption(f"- {note}")

    tab_prep, tab_live = st.tabs(["Prep Brief", "Live Card"])
    with tab_prep:
        for section in brief.sections:
            _render_section(case, section)
    with tab_live:
        _render_live_card(case, brief)

    st.subheader("Downloads")
    include_live_notes = st.checkbox("Include live notes in the Markdown export", value=False, key="export_include_live_notes")
    markdown = brief_service.render_brief_markdown(brief, include_live_notes=include_live_notes)
    st.download_button("Download negotiation_brief.md", markdown, file_name="negotiation_brief.md", key="download_brief_md")
    st.download_button(
        "Download negotiation_case.json", brief_service.export_case_json(case), file_name="negotiation_case.json", key="download_case_json"
    )
    if st.checkbox("Include pipeline_trace.json", value=False, key="export_include_trace"):
        st.download_button(
            "Download pipeline_trace.json", brief_service.export_pipeline_trace(case), file_name="pipeline_trace.json", key="download_trace_json"
        )
