"""ingest_material(): the orchestration step between "user uploads a file"
and "it's ready for organization and consolidation" (SPEC §4, §12 Page 1).
Wired into the Materials page (negotiation_copilot/pages/materials.py)."""

import time

import pymupdf as fitz
import pytest

from negotiation_copilot import document_parser
from negotiation_copilot.config import Config
from negotiation_copilot.document_parser import UploadRejected
from negotiation_copilot.fake_clients import FakeAIClient
from negotiation_copilot.ingestion_service import file_type_for, ingest_material, ingest_materials_batch, organize_and_consolidate
from negotiation_copilot.models import DocumentExtraction, RelationshipCue

TXT_BODY = b"This is a shared context paragraph.\n\nThis is a second paragraph about the deadline."

LONG_PARAGRAPH = (
    "This role brief describes the negotiation context in enough detail to read "
    "as a normal business document, well above any low-density threshold for a page."
)


def _config(tmp_path, max_upload_mb=25, max_pdf_pages=50):
    return Config(
        openai_api_key=None, openai_model=None, openai_store_responses=False, run_live_openai_tests=False,
        app_data_dir=tmp_path, max_upload_mb=max_upload_mb, max_pdf_pages=max_pdf_pages, log_level="INFO",
    )


def _pdf_bytes(page_texts: list[str | None]) -> bytes:
    doc = fitz.open()
    for text in page_texts:
        page = doc.new_page()
        if text:
            page.insert_text((72, 72), text, fontsize=11)
    return doc.tobytes()


def test_file_type_for_maps_known_extensions():
    assert file_type_for("brief.pdf") == "pdf"
    assert file_type_for("brief.DOCX") == "docx"
    assert file_type_for("notes.md") == "md"
    assert file_type_for("notes.txt") == "txt"


def test_ingest_material_routes_txt_through_document_parser(tmp_path):
    record, cues, extraction = ingest_material(
        "shared_case.txt", TXT_BODY, "shared", 0,
        config=_config(tmp_path), ai_client=FakeAIClient(),
    )

    assert record.file_type == "txt"
    assert record.scope == "shared"
    assert record.upload_index == 0
    assert record.parse_method == "txt"
    assert record.paragraph_count == 2
    assert record.page_count is None
    assert record.sha256 == document_parser.sha256_of(TXT_BODY)
    assert record.processing_status == "processed"
    assert isinstance(cues, list) and all(isinstance(c, RelationshipCue) for c in cues)
    assert isinstance(extraction, DocumentExtraction)
    assert extraction.document_id == record.document_id


def test_ingest_material_routes_pdf_through_pdf_service(tmp_path):
    data = _pdf_bytes([LONG_PARAGRAPH, None])

    record, _cues, extraction = ingest_material(
        "brief.pdf", data, "my_confidential", 1,
        config=_config(tmp_path), ai_client=FakeAIClient(),
    )

    assert record.file_type == "pdf"
    assert record.parse_method == "pdf"
    assert record.page_count == 2
    assert record.page_reading_methods[1] == "native_text"
    # Page 2 is blank: native extraction alone can't resolve it, so it's
    # routed to the AI reading fallback, which (in fake mode) still can't
    # invent content to fill the gap (see docs/DECISIONS.md) and leaves it
    # flagged for review rather than fabricating a result.
    assert record.pages_needing_review == [2]
    assert extraction.document_id == record.document_id


def test_ingest_material_propagates_upload_rejected_without_partial_side_effects(tmp_path):
    with pytest.raises(UploadRejected):
        ingest_material(
            "malware.exe", b"MZ\x90\x00fake", "shared", 0,
            config=_config(tmp_path), ai_client=FakeAIClient(),
        )


def test_ingest_material_enforces_running_total_budget(tmp_path):
    small_cfg = _config(tmp_path, max_upload_mb=1)
    one_mb = 1024 * 1024
    data = b"x" * (one_mb - 100)

    with pytest.raises(UploadRejected):
        ingest_material(
            "second.txt", data, "shared", 1,
            config=small_cfg, ai_client=FakeAIClient(), running_total_bytes=one_mb,
        )


class _FailingAIClient:
    """Stands in for a real backend whose AI call times out or errors —
    e.g. ClaudeCliClient hitting a subprocess timeout on a large document.
    ingest_material must degrade this one document, not crash the batch."""

    def extract_relationship_cues(self, request):
        raise RuntimeError("simulated cue-extraction timeout")

    def extract_document(self, request):
        raise RuntimeError("simulated extraction timeout")


def test_ingest_material_degrades_gracefully_when_cue_extraction_fails(tmp_path):
    record, cues, extraction = ingest_material(
        "shared_case.txt", TXT_BODY, "shared", 0,
        config=_config(tmp_path), ai_client=_FailingAIClient(),
    )

    assert record.processing_status == "processed"  # parsing itself still succeeded
    assert cues == []
    assert any("cue extraction failed" in w.lower() for w in record.warnings)


def test_ingest_material_degrades_gracefully_when_extraction_fails(tmp_path):
    record, _cues, extraction = ingest_material(
        "shared_case.txt", TXT_BODY, "shared", 0,
        config=_config(tmp_path), ai_client=_FailingAIClient(),
    )

    assert extraction.document_id == record.document_id
    assert extraction.summary.bullets == []  # honest empty placeholder, not fabricated
    assert any("extraction failed" in w.lower() for w in record.warnings)


# --- ingest_materials_batch: concurrent per-document AI calls ---


class _SlowAIClient(FakeAIClient):
    """Real FakeAIClient behavior, but each of the two per-document AI calls
    sleeps first — simulates real network/subprocess latency so a test can
    tell concurrent processing apart from sequential processing by wall clock."""

    def __init__(self, delay_s: float):
        super().__init__()
        self._delay_s = delay_s

    def extract_relationship_cues(self, request):
        time.sleep(self._delay_s)
        return super().extract_relationship_cues(request)

    def extract_document(self, request):
        time.sleep(self._delay_s)
        return super().extract_document(request)


def _files(n: int) -> list[tuple[str, bytes, str]]:
    return [(f"doc{i}.txt", f"This is document number {i}, a shared context paragraph.".encode(), "shared") for i in range(n)]


def test_ingest_materials_batch_processes_every_file(tmp_path):
    results = ingest_materials_batch(_files(4), config=_config(tmp_path), ai_client=FakeAIClient())

    assert len(results) == 4
    assert [r.filename for r in results] == [f"doc{i}.txt" for i in range(4)]
    assert all(r.error is None for r in results)
    assert all(r.record is not None and r.extraction is not None for r in results)
    assert {r.record.upload_index for r in results} == {0, 1, 2, 3}


def test_ingest_materials_batch_runs_ai_calls_concurrently_not_sequentially(tmp_path):
    delay = 0.2
    slow_client = _SlowAIClient(delay)

    started = time.monotonic()
    results = ingest_materials_batch(_files(4), config=_config(tmp_path), ai_client=slow_client, max_workers=4)
    elapsed = time.monotonic() - started

    assert len(results) == 4
    sequential_baseline = 4 * 2 * delay  # 4 files x 2 AI calls x delay, if run one at a time
    assert elapsed < sequential_baseline / 2  # concurrent must be well under half the sequential time


def test_ingest_materials_batch_reports_monotonic_progress(tmp_path):
    seen = []
    ingest_materials_batch(
        _files(3), config=_config(tmp_path), ai_client=FakeAIClient(),
        on_progress=lambda done, total: seen.append((done, total)),
    )
    assert [t for _, t in seen] == [3, 3, 3]
    assert [d for d, _ in seen] == sorted(d for d, _ in seen)
    assert seen[-1] == (3, 3)


def test_ingest_materials_batch_one_rejected_file_does_not_block_others(tmp_path):
    files = [
        ("good1.txt", b"A perfectly fine shared document.", "shared"),
        ("malware.exe", b"MZ\x90\x00fake", "shared"),
        ("good2.txt", b"Another perfectly fine shared document.", "shared"),
    ]
    results = ingest_materials_batch(files, config=_config(tmp_path), ai_client=FakeAIClient())

    by_name = {r.filename: r for r in results}
    assert by_name["good1.txt"].error is None
    assert by_name["good2.txt"].error is None
    assert by_name["malware.exe"].error is not None
    assert by_name["malware.exe"].record is None


def test_ingest_materials_batch_degrades_one_ai_failure_without_affecting_others(tmp_path):
    class _FlakyOnOneFile(FakeAIClient):
        def extract_document(self, request):
            if request.filename == "flaky.txt":
                raise RuntimeError("simulated timeout")
            return super().extract_document(request)

    files = [("flaky.txt", b"Content that triggers a simulated failure.", "shared"), ("fine.txt", b"Content that works fine.", "shared")]
    results = ingest_materials_batch(files, config=_config(tmp_path), ai_client=_FlakyOnOneFile())

    by_name = {r.filename: r for r in results}
    assert by_name["flaky.txt"].error is None  # an AI-call failure is a degradation, not a batch "error"
    assert any("extraction failed" in w.lower() for w in by_name["flaky.txt"].record.warnings)
    assert by_name["fine.txt"].record.warnings == []


# --- organize_and_consolidate: the two independent AI calls run concurrently ---


def _two_ingested_documents(tmp_path):
    cfg = _config(tmp_path)
    client = FakeAIClient()
    doc1, cues1, ext1 = ingest_material("shared_case.txt", TXT_BODY, "shared", 0, config=cfg, ai_client=client)
    doc2, cues2, ext2 = ingest_material(
        "second.txt", b"A second shared paragraph about the same deal.", "shared", 1, config=cfg, ai_client=client
    )
    return [doc1, doc2], cues1 + cues2, [ext1, ext2]


def test_organize_and_consolidate_returns_case_with_organization_attached(tmp_path):
    documents, cues, extractions = _two_ingested_documents(tmp_path)
    case = organize_and_consolidate(documents, cues, extractions, ai_client=FakeAIClient())

    assert case.documents == documents
    assert case.organization is not None
    assert case.organization.review_status == "unreviewed"  # never auto-confirmed


class _SlowOrgAndConsolidateClient(FakeAIClient):
    def __init__(self, delay_s: float):
        super().__init__()
        self._delay_s = delay_s

    def organize_materials(self, request):
        time.sleep(self._delay_s)
        return super().organize_materials(request)

    def consolidate_case(self, request):
        time.sleep(self._delay_s)
        return super().consolidate_case(request)


def test_organize_and_consolidate_runs_the_two_ai_calls_concurrently(tmp_path):
    documents, cues, extractions = _two_ingested_documents(tmp_path)
    delay = 0.2
    slow_client = _SlowOrgAndConsolidateClient(delay)

    started = time.monotonic()
    organize_and_consolidate(documents, cues, extractions, ai_client=slow_client)
    elapsed = time.monotonic() - started

    sequential_baseline = 2 * delay  # if organize then consolidate ran one after the other
    assert elapsed < sequential_baseline * 0.75


def test_ingest_materials_batch_enforces_running_total_budget_in_upload_order(tmp_path):
    small_cfg = _config(tmp_path, max_upload_mb=1)
    one_mb = 1024 * 1024
    chunk = b"x" * (one_mb // 2 + 1000)  # just over half a MB each; two together exceed 1MB

    files = [("first.txt", chunk, "shared"), ("second.txt", chunk, "shared")]
    results = ingest_materials_batch(files, config=small_cfg, ai_client=FakeAIClient())

    by_name = {r.filename: r for r in results}
    assert by_name["first.txt"].error is None
    assert by_name["second.txt"].error is not None
