"""Page 2 — Pipeline & Relationships (SPEC §6.3, §12)."""

import streamlit as st

from ._common import get_case

_CONFIDENCE_EMOJI = {"high": "🟢", "medium": "🟡", "low": "🔴"}


def _document_lookup(case):
    return {doc.document_id: doc for doc in case.documents}


def _label_for(doc_lookup, document_id):
    doc = doc_lookup.get(document_id)
    return doc.filename if doc else document_id


def _order_by_upload(case):
    return [d.document_id for d in sorted(case.documents, key=lambda d: d.upload_index)]


def _order_by_filename(case):
    return [d.document_id for d in sorted(case.documents, key=lambda d: d.filename.lower())]


def _render_order_column(name, order, doc_lookup):
    st.markdown(f"**{name}**")
    if not order:
        st.caption("—")
        return
    for i, doc_id in enumerate(order, start=1):
        st.write(f"{i}. {_label_for(doc_lookup, doc_id)}")


def _render_temporal_section(case, org) -> None:
    doc_lookup = _document_lookup(case)
    upload_order = _order_by_upload(case)
    filename_order = _order_by_filename(case)
    ai_order = org.proposed_order or []

    st.subheader("Order comparison")
    st.caption("Filenames never override body text — compare all three before accepting one.")
    cols = st.columns(3)
    with cols[0]:
        _render_order_column("Upload order", upload_order, doc_lookup)
    with cols[1]:
        _render_order_column("Filename order", filename_order, doc_lookup)
    with cols[2]:
        _render_order_column("AI proposed order", ai_order, doc_lookup)

    st.subheader("Accept or edit")
    choice = st.radio(
        "Which order should this case use?",
        ["AI proposed order", "Upload order", "Filename order", "Custom"],
        key="org_order_choice",
        horizontal=True,
    )
    if choice == "AI proposed order":
        chosen_order = ai_order
    elif choice == "Upload order":
        chosen_order = upload_order
    elif choice == "Filename order":
        chosen_order = filename_order
    else:
        all_ids = [d.document_id for d in case.documents]
        chosen_order = st.multiselect(
            "Custom order — pick documents in the order you want",
            options=all_ids,
            format_func=lambda doc_id: _label_for(doc_lookup, doc_id),
            key="org_custom_order",
        )

    if st.button("Accept this order", disabled=not chosen_order):
        status = "confirmed" if chosen_order == ai_order else "edited_by_user"
        case.organization = org.model_copy(update={"confirmed_order": chosen_order, "review_status": status})
        st.success(f"Order {status.replace('_', ' ')}.")
        st.rerun()

    if org.confirmed_order:
        st.caption(f"Currently confirmed order: {[_label_for(doc_lookup, d) for d in org.confirmed_order]}")


def _render_grouped_section(case, org) -> None:
    doc_lookup = _document_lookup(case)
    if org.groups:
        st.subheader("Groups")
        for group in org.groups:
            with st.expander(f"{group.name} ({len(group.document_ids)} document(s))"):
                st.caption(group.organizing_reason)
                for doc_id in group.document_ids:
                    st.write(f"- {_label_for(doc_lookup, doc_id)}")
    else:
        st.subheader("Index")
        st.caption("No order or grouping is asserted for independent materials.")
        for doc in case.documents:
            st.write(f"- {doc.filename}")

    if st.button("Accept this grouping"):
        case.organization = org.model_copy(update={"review_status": "confirmed"})
        st.success("Grouping confirmed.")
        st.rerun()


def _render_relationship_cues(case) -> None:
    if not case.relationship_cues:
        return
    st.subheader("Relationship cues")
    doc_lookup = _document_lookup(case)
    by_doc: dict[str, list] = {}
    for cue in case.relationship_cues:
        by_doc.setdefault(cue.document_id, []).append(cue)

    for doc_id, cues in by_doc.items():
        with st.expander(f"{_label_for(doc_lookup, doc_id)} — {len(cues)} cue(s)"):
            for cue in cues:
                location = f"p.{cue.page_number}" if cue.page_number is not None else (cue.paragraph_id or "—")
                st.markdown(f"- **{cue.cue_type}** ({location}): {cue.normalized_value or '_none_'} — “{cue.excerpt}”")
            st.json([c.model_dump(mode="json") for c in cues])


def render() -> None:
    st.title("Pipeline & Relationships")
    st.caption("Per-page reading status, relationship judgment, and structured intermediates.")

    case = get_case()

    st.info(
        "PDF reading routing is not implemented yet (see docs/TASKS.md T2.2+). "
        "Relationship judgment below reflects the demo fixture / whatever the pipeline has produced so far."
    )

    _render_relationship_cues(case)

    org = case.organization
    if org is None:
        st.write("No organization result yet.")
        return

    st.subheader("Relationship mode")
    emoji = _CONFIDENCE_EMOJI.get(org.confidence, "⚪")
    st.markdown(f"### {emoji} {org.organization_mode}  ·  confidence: {org.confidence}")
    if org.rationale:
        st.write(org.rationale)
    st.caption(f"Review status: {org.review_status}")

    if org.unresolved_ambiguities:
        st.subheader("Unresolved ambiguities")
        for item in org.unresolved_ambiguities:
            st.warning(item)

    if org.temporal_order_applicable:
        _render_temporal_section(case, org)
    else:
        _render_grouped_section(case, org)

    if org.relations:
        st.subheader("Pairwise relations")
        for rel in org.relations:
            st.markdown(
                f"- `{rel.source_document_id}` → **{rel.relation_type}** "
                f"({rel.confidence} confidence): {rel.explanation}"
            )

    with st.expander("Raw organization JSON"):
        st.json(org.model_dump(mode="json"))
