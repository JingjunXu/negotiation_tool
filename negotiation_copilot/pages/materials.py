"""Page 1 — Materials (SPEC §4, §6, §12 Page 1)."""

import streamlit as st

from ..config import config
from ..document_parser import UploadRejected
from ..ingestion_service import ingest_material, ingest_materials_batch, organize_and_consolidate
from ..models import MaterialScope, NegotiationCase
from ._common import get_ai_client, get_case, is_demo_case, set_case

_SCOPES: list[MaterialScope] = ["shared", "my_confidential", "instructor_rules"]
_SCOPE_LABELS = {
    "shared": "Shared with counterpart",
    "my_confidential": "My confidential",
    "instructor_rules": "Instructor rules",
}


def render() -> None:
    st.title("Materials")
    st.caption("Upload or paste negotiation materials and set a scope for each one.")

    case = get_case()
    ai_client = get_ai_client()

    if is_demo_case():
        st.info("Showing a demo case. Upload or paste your own materials below to start a real one.")

    _render_uploader(ai_client)
    st.divider()
    _render_paste_form(ai_client)
    st.divider()
    _render_material_list(case)
    st.divider()
    _render_organize_consolidate(case, ai_client)


def _start_real_case_if_needed() -> NegotiationCase:
    """Real materials should never be appended onto the seeded demo
    fixture's documents — start a fresh empty case the first time the user
    processes something real."""
    if is_demo_case():
        set_case(NegotiationCase())
    return get_case()


def _ingest_and_append(case: NegotiationCase, ai_client, filename: str, data: bytes, scope: MaterialScope) -> None:
    running_total = sum(d.size_bytes for d in case.documents)
    record, cues, extraction = ingest_material(
        filename,
        data,
        scope,
        len(case.documents),
        config=config,
        ai_client=ai_client,
        running_total_bytes=running_total,
    )
    case.documents.append(record)
    case.relationship_cues.extend(cues)
    case.document_extractions.append(extraction)


def _render_uploader(ai_client) -> None:
    st.subheader("Upload files")
    uploaded_files = st.file_uploader(
        "PDF, DOCX, TXT, or Markdown",
        type=["pdf", "docx", "txt", "md"],
        accept_multiple_files=True,
        key="materials_uploader",
    )
    if not uploaded_files:
        return

    scopes: dict[str, MaterialScope] = {}
    for f in uploaded_files:
        scopes[f.name] = st.selectbox(
            f"Scope for {f.name}",
            options=_SCOPES,
            format_func=lambda s: _SCOPE_LABELS[s],
            key=f"materials_scope_{f.name}",
        )

    if st.button("Process uploaded files", key="materials_process_uploads"):
        case = _start_real_case_if_needed()
        running_total = sum(d.size_bytes for d in case.documents)
        files = [(f.name, f.getvalue(), scopes[f.name]) for f in uploaded_files]

        progress_text = st.empty()
        progress_bar = st.progress(0.0)
        progress_text.write(f"Reading and extracting {len(files)} file(s) (running up to {config.ingestion_max_concurrency} at once)...")

        def _on_progress(done: int, total: int) -> None:
            progress_text.write(f"Extracted {done}/{total}...")
            progress_bar.progress(done / total)

        results = ingest_materials_batch(
            files,
            config=config,
            ai_client=ai_client,
            starting_upload_index=len(case.documents),
            running_total_bytes=running_total,
            on_progress=_on_progress,
        )
        progress_text.empty()
        progress_bar.empty()

        processed = 0
        for result in results:
            if result.error:
                st.error(f"{result.filename}: rejected — {result.error}")
                continue
            case.documents.append(result.record)
            case.relationship_cues.extend(result.cues)
            case.document_extractions.append(result.extraction)
            processed += 1
        if processed:
            st.success(f"Processed {processed} of {len(files)} file(s).")
            st.rerun()


def _render_paste_form(ai_client) -> None:
    st.subheader("Or paste text")
    with st.form("materials_paste_form", clear_on_submit=True):
        label = st.text_input("Label for this text (used as filename)", value="pasted_note.txt", key="materials_paste_label")
        scope = st.selectbox("Scope", options=_SCOPES, format_func=lambda s: _SCOPE_LABELS[s], key="materials_paste_scope")
        text = st.text_area("Paste text", height=200, key="materials_paste_text")
        submitted = st.form_submit_button("Process pasted text", key="materials_paste_submit")

    if not submitted:
        return
    if not text.strip():
        st.error("Paste some text first.")
        return

    filename = label.strip() or "pasted_note.txt"
    if not filename.lower().endswith((".txt", ".md")):
        filename += ".txt"

    case = _start_real_case_if_needed()
    try:
        _ingest_and_append(case, ai_client, filename, text.encode("utf-8"), scope)
    except UploadRejected as exc:
        st.error(str(exc))
        return
    st.success(f"Processed {filename}.")
    st.rerun()


def _render_material_list(case: NegotiationCase) -> None:
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
            if doc.page_reading_methods:
                methods = list(doc.page_reading_methods.values())
                native = sum(1 for m in methods if m == "native_text")
                ai_assisted = len(methods) - native
                st.caption(f"Reading methods: {native} native, {ai_assisted} AI-assisted")
            if doc.pages_needing_review:
                st.warning(f"Pages needing review: {doc.pages_needing_review}")
            for warning in doc.warnings:
                st.warning(warning)


def _render_organize_consolidate(case: NegotiationCase, ai_client) -> None:
    st.subheader("Organize and consolidate")
    if not case.documents:
        st.caption("Upload or paste materials first.")
        return
    st.caption(
        "Runs cross-document organization, then consolidates everything into "
        "the working case. This replaces the current working case."
    )
    if st.button("Organize + Consolidate", key="materials_organize_consolidate"):
        with st.spinner("Organizing and consolidating materials — two AI calls running concurrently, this can take a minute or two..."):
            new_case = organize_and_consolidate(
                case.documents, case.relationship_cues, case.document_extractions, ai_client=ai_client
            )
        new_case.relationship_cues = case.relationship_cues
        set_case(new_case)
        st.success("Materials organized and consolidated.")
        st.rerun()
