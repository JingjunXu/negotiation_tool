"""Material ingestion (SPEC §4, §12 Page 1): validate an upload, route it
through native/AI PDF reading or plain document parsing, and extract
relationship cues + a per-document structured extraction — the steps
between "user uploads a file" and "it's ready for organization and
consolidation." Kept out of the page module so it's testable without
Streamlit (CLAUDE.md: "Do not build prompts inside Streamlit page code" —
the same spirit applies to pipeline orchestration).
"""

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable
from uuid import uuid4

from . import consolidation_service, document_parser, extraction_service, pdf_service
from . import material_organization_service as mos
from .ai_client import AIClient, DocumentMeta
from .config import Config
from .material_organization_service import (
    extract_relationship_cues,
    text_units_from_paragraphs,
    text_units_from_pdf_pages,
)
from .models import DocumentExtraction, DocumentRecord, DocumentSummary, MaterialScope, NegotiationCase, RelationshipCue

_EXT_TO_TYPE = {".pdf": "pdf", ".docx": "docx", ".txt": "txt", ".md": "md"}


def file_type_for(filename: str) -> str:
    return _EXT_TO_TYPE.get(Path(filename).suffix.lower(), "txt")


def _prepare_material(
    filename: str,
    data: bytes,
    scope: MaterialScope,
    upload_index: int,
    *,
    config: Config,
    ai_client: AIClient,
    running_total_bytes: int,
) -> tuple[DocumentRecord, list]:
    """Validate and parse/read one file — everything that must stay
    sequential (the running-total size budget is enforced in upload order)
    and is fast anyway (no per-document AI extraction call here). Raises
    `document_parser.UploadRejected` unchanged on a failed safety check.
    """
    document_parser.validate_upload(filename, data, config=config, running_total_bytes=running_total_bytes)

    document_id = uuid4().hex
    file_type = file_type_for(filename)

    if file_type == "pdf":
        pages = pdf_service.read_pdf(document_id, filename, data, config=config, ai_client=ai_client)
        units = text_units_from_pdf_pages(pages)
        record = DocumentRecord(
            document_id=document_id,
            filename=filename,
            upload_index=upload_index,
            file_type="pdf",
            size_bytes=len(data),
            sha256=document_parser.sha256_of(data),
            page_count=len(pages),
            parse_method="pdf",
            page_reading_methods={p.page_number: p.reading_method for p in pages},
            pages_needing_review=[p.page_number for p in pages if p.status != "success"],
            scope=scope,
            processing_status="processed",
        )
    else:
        paragraphs = document_parser.parse_document(document_id, data, file_type, app_data_dir=config.app_data_dir)
        units = text_units_from_paragraphs(paragraphs)
        record = DocumentRecord(
            document_id=document_id,
            filename=filename,
            upload_index=upload_index,
            file_type=file_type,
            size_bytes=len(data),
            sha256=document_parser.sha256_of(data),
            paragraph_count=len(paragraphs),
            parse_method=file_type,
            scope=scope,
            processing_status="processed",
        )

    return record, units


def _enrich_material(
    record: DocumentRecord, units: list, *, ai_client: AIClient
) -> tuple[list[RelationshipCue], DocumentExtraction]:
    """The two real per-document AI calls — the slow part, and the part
    that's safe to run concurrently across documents, since nothing about
    one document's extraction depends on any other document's.

    A slow/failing call (timeout, transient API error, ...) must never
    discard a document that was successfully read/parsed above, and must
    never take down a whole batch of other documents being ingested in
    the same pass (see docs/DECISIONS.md) — degrade this one document
    honestly instead, the same "don't fabricate, don't crash" pattern
    FakeAIClient already uses for stages it can't safely answer.
    """
    try:
        cues = extract_relationship_cues(record.document_id, record.filename, units, ai_client=ai_client)
    except Exception as exc:
        cues = []
        record.warnings.append(f"Relationship cue extraction failed, skipped: {exc}")

    try:
        extraction = extraction_service.extract_document(record.document_id, record.filename, units, ai_client=ai_client)
    except Exception as exc:
        extraction = DocumentExtraction(document_id=record.document_id, summary=DocumentSummary(bullets=[]))
        record.warnings.append(f"Structured extraction failed, left empty: {exc}")

    return cues, extraction


def ingest_material(
    filename: str,
    data: bytes,
    scope: MaterialScope,
    upload_index: int,
    *,
    config: Config,
    ai_client: AIClient,
    running_total_bytes: int = 0,
) -> tuple[DocumentRecord, list[RelationshipCue], DocumentExtraction]:
    """Validate, parse/read, and extract one uploaded file. Raises
    `document_parser.UploadRejected` unchanged if the file fails a safety
    check — the caller decides how to surface that; nothing is appended
    anywhere by this function, it only builds and returns the records.

    For more than a couple of files, prefer `ingest_materials_batch` — it
    runs the slow per-document AI calls concurrently instead of one at a
    time (see docs/DECISIONS.md)."""
    record, units = _prepare_material(
        filename, data, scope, upload_index, config=config, ai_client=ai_client, running_total_bytes=running_total_bytes
    )
    cues, extraction = _enrich_material(record, units, ai_client=ai_client)
    return record, cues, extraction


@dataclass
class IngestResult:
    """One file's outcome from `ingest_materials_batch`. `error` is set only
    for a validation-time rejection (the file was never parsed at all);
    an AI-call failure during enrichment is NOT an error here — it's
    already been degraded into a warning on `record` by `_enrich_material`."""

    filename: str
    record: DocumentRecord | None = None
    cues: list[RelationshipCue] = field(default_factory=list)
    extraction: DocumentExtraction | None = None
    error: str | None = None


def ingest_materials_batch(
    files: list[tuple[str, bytes, MaterialScope]],
    *,
    config: Config,
    ai_client: AIClient,
    starting_upload_index: int = 0,
    running_total_bytes: int = 0,
    max_workers: int | None = None,
    on_progress: Callable[[int, int], None] | None = None,
) -> list[IngestResult]:
    """Ingest many files, running the slow per-document AI calls
    concurrently across files instead of one at a time.

    Validation and parsing stay sequential in upload order — they're fast,
    and the running-total size budget must be enforced in that order — but
    the two real AI calls per document are independent of every other
    document, so they're the part that actually benefits from concurrency
    (see docs/DECISIONS.md: sequential real AI calls across dozens of PDFs
    was the main source of long processing times).

    `on_progress(done, total)` is called from the calling thread (never
    from a worker thread) as each document's enrichment completes, so a
    caller can safely update a Streamlit progress indicator from it.
    """
    results: list[IngestResult | None] = [None] * len(files)
    prepared: list[tuple[int, DocumentRecord, list]] = []
    total_bytes = running_total_bytes

    for i, (filename, data, scope) in enumerate(files):
        try:
            record, units = _prepare_material(
                filename, data, scope, starting_upload_index + i,
                config=config, ai_client=ai_client, running_total_bytes=total_bytes,
            )
        except document_parser.UploadRejected as exc:
            results[i] = IngestResult(filename=filename, error=str(exc))
            continue
        total_bytes += len(data)
        prepared.append((i, record, units))

    if prepared:
        workers = max_workers or config.ingestion_max_concurrency
        done = 0
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(_enrich_material, record, units, ai_client=ai_client): (i, record) for i, record, units in prepared}
            for future in as_completed(futures):
                i, record = futures[future]
                cues, extraction = future.result()
                results[i] = IngestResult(filename=record.filename, record=record, cues=cues, extraction=extraction)
                done += 1
                if on_progress:
                    on_progress(done, len(prepared))

    return results


def organize_and_consolidate(
    documents: list[DocumentRecord],
    cues: list[RelationshipCue],
    extractions: list[DocumentExtraction],
    *,
    ai_client: AIClient,
) -> NegotiationCase:
    """Run `organize_materials` and `consolidate_case`'s AI call
    concurrently instead of one after the other.

    `consolidate_case`'s AI call only ever reads `documents`/`extractions`
    — it never reads the `organization` result, `organization` is only
    attached to the returned case afterward (see docs/DECISIONS.md) — so
    the two calls are independent and there's no reason to make the user
    wait for one to finish before starting the other.
    """
    doc_metas = [DocumentMeta(document_id=d.document_id, filename=d.filename, upload_index=d.upload_index) for d in documents]

    with ThreadPoolExecutor(max_workers=2) as pool:
        organization_future = pool.submit(mos.organize_materials, doc_metas, cues, ai_client=ai_client)
        case_future = pool.submit(consolidation_service.consolidate_case, documents, None, extractions, ai_client=ai_client)
        organization = organization_future.result()
        case = case_future.result()

    case.organization = organization
    return case
