import pymupdf as fitz
import pytest

from negotiation_copilot import pdf_service
from negotiation_copilot.ai_client import ReadPDFRequest
from negotiation_copilot.config import Config
from negotiation_copilot.models import PDFPageResult

LONG_PARAGRAPH = (
    "This role brief describes the negotiation context in enough detail to read "
    "as a normal business document, well above any low-density threshold for a page."
)


def _config(tmp_path, max_pdf_pages=50):
    return Config(
        openai_api_key=None,
        openai_model=None,
        openai_store_responses=False,
        run_live_openai_tests=False,
        app_data_dir=tmp_path,
        max_upload_mb=25,
        max_pdf_pages=max_pdf_pages,
        log_level="INFO",
    )


def _pdf_bytes(page_texts: list[str | None]) -> bytes:
    doc = fitz.open()
    for text in page_texts:
        page = doc.new_page()
        if text:
            page.insert_text((72, 72), text, fontsize=11)
    return doc.tobytes()


class _StubAIClient:
    def __init__(self, results_by_page: dict[int, PDFPageResult]):
        self._results_by_page = results_by_page
        self.last_request: ReadPDFRequest | None = None

    def read_pdf(self, request: ReadPDFRequest) -> list[PDFPageResult]:
        self.last_request = request
        return [self._results_by_page[p] for p in request.page_numbers if p in self._results_by_page]


def test_no_ai_client_leaves_insufficient_pages_needing_review(tmp_path):
    data = _pdf_bytes([LONG_PARAGRAPH, None])
    results = pdf_service.read_pdf("doc-1", "brief.pdf", data, config=_config(tmp_path), ai_client=None)
    assert results[0].status == "success"
    assert results[0].reading_method == "native_text"
    assert results[1].status == "needs_review"
    assert results[1].reading_method == "native_text"


def test_ai_client_only_called_for_insufficient_pages(tmp_path):
    data = _pdf_bytes([LONG_PARAGRAPH, None, LONG_PARAGRAPH])
    stub = _StubAIClient(
        {
            2: PDFPageResult(
                document_id="doc-1",
                page_number=2,
                reading_method="ai_pdf",
                content="Recovered content",
                key_items=[],
                quality_flags=[],
                status="success",
            )
        }
    )
    results = pdf_service.read_pdf("doc-1", "brief.pdf", data, config=_config(tmp_path), ai_client=stub)

    assert stub.last_request.page_numbers == [2]
    assert results[0].reading_method == "native_text"
    assert results[1].reading_method == "ai_pdf"
    assert results[1].status == "success"
    assert results[1].content == "Recovered content"
    assert results[2].reading_method == "native_text"


def test_unreadable_region_stays_needs_review_not_invented(tmp_path):
    data = _pdf_bytes([None])
    stub = _StubAIClient(
        {
            1: PDFPageResult(
                document_id="doc-1",
                page_number=1,
                reading_method="ai_pdf",
                content="",
                key_items=[],
                quality_flags=["illegible_region"],
                status="needs_review",
            )
        }
    )
    results = pdf_service.read_pdf("doc-1", "brief.pdf", data, config=_config(tmp_path), ai_client=stub)
    assert results[0].status == "needs_review"
    assert results[0].content == ""


def test_both_routes_produce_identical_shape(tmp_path):
    data = _pdf_bytes([LONG_PARAGRAPH, None])
    stub = _StubAIClient(
        {
            2: PDFPageResult(
                document_id="doc-1",
                page_number=2,
                reading_method="ai_pdf",
                content="Recovered",
                key_items=[],
                quality_flags=[],
                status="success",
            )
        }
    )
    results = pdf_service.read_pdf("doc-1", "brief.pdf", data, config=_config(tmp_path), ai_client=stub)
    for result in results:
        assert isinstance(result, PDFPageResult)
        assert set(type(result).model_fields.keys()) == set(PDFPageResult.model_fields.keys())


def test_enforces_max_pdf_pages(tmp_path):
    data = _pdf_bytes([LONG_PARAGRAPH, LONG_PARAGRAPH, LONG_PARAGRAPH])
    with pytest.raises(pdf_service.TooManyPagesError):
        pdf_service.read_pdf("doc-1", "brief.pdf", data, config=_config(tmp_path, max_pdf_pages=2), ai_client=None)


class _CountingAIClient:
    cache_tag = "counting"

    def __init__(self, result: PDFPageResult):
        self._result = result
        self.call_count = 0

    def read_pdf(self, request: ReadPDFRequest) -> list[PDFPageResult]:
        self.call_count += 1
        return [self._result]


def test_identical_content_reuses_cached_result_instead_of_calling_ai_again(tmp_path):
    data = _pdf_bytes([LONG_PARAGRAPH, None])
    stub = _CountingAIClient(
        PDFPageResult(
            document_id="doc-1", page_number=2, reading_method="ai_pdf", content="Cached content",
            key_items=[], quality_flags=[], status="success",
        )
    )
    cfg = _config(tmp_path)

    first = pdf_service.read_pdf("doc-1", "brief.pdf", data, config=cfg, ai_client=stub)
    second = pdf_service.read_pdf("doc-2", "brief.pdf", data, config=cfg, ai_client=stub)

    assert stub.call_count == 1
    assert first[1].content == "Cached content"
    assert second[1].content == "Cached content"
    assert second[1].document_id == "doc-2"  # re-tagged for the new caller, not stale from the first call


def test_cache_does_not_cross_fake_and_real_client_boundaries(tmp_path):
    data = _pdf_bytes([LONG_PARAGRAPH, None])
    cfg = _config(tmp_path)

    fake_stub = _CountingAIClient(
        PDFPageResult(
            document_id="doc-1", page_number=2, reading_method="ai_pdf", content="Fake placeholder",
            key_items=[], quality_flags=["fake_mode_no_ai_reading"], status="needs_review",
        )
    )
    fake_stub.cache_tag = "fake"
    real_stub = _CountingAIClient(
        PDFPageResult(
            document_id="doc-1", page_number=2, reading_method="ai_pdf", content="Real AI reading",
            key_items=[], quality_flags=[], status="success",
        )
    )
    real_stub.cache_tag = "openai:gpt-test"

    first = pdf_service.read_pdf("doc-1", "brief.pdf", data, config=cfg, ai_client=fake_stub)
    second = pdf_service.read_pdf("doc-1", "brief.pdf", data, config=cfg, ai_client=real_stub)

    assert fake_stub.call_count == 1
    assert real_stub.call_count == 1
    assert first[1].content == "Fake placeholder"
    assert second[1].content == "Real AI reading"


class _FlakyPerPageAIClient:
    cache_tag = "flaky"

    def __init__(self, always_fail_pages: set[int]):
        self._always_fail_pages = always_fail_pages
        self.batch_calls = 0
        self.per_page_calls = 0

    def read_pdf(self, request: ReadPDFRequest) -> list[PDFPageResult]:
        if len(request.page_numbers) > 1:
            self.batch_calls += 1
            raise RuntimeError("simulated transient batch failure")

        self.per_page_calls += 1
        [page_number] = request.page_numbers
        if page_number in self._always_fail_pages:
            raise RuntimeError(f"simulated persistent failure on page {page_number}")
        return [
            PDFPageResult(
                document_id=request.document_id, page_number=page_number, reading_method="ai_pdf",
                content=f"Recovered page {page_number}", key_items=[], quality_flags=[], status="success",
            )
        ]


def test_batch_failure_degrades_to_per_page_and_preserves_native_fallback_for_stubborn_page(tmp_path):
    data = _pdf_bytes([None, None])  # both pages need review
    stub = _FlakyPerPageAIClient(always_fail_pages={2})

    results = pdf_service.read_pdf("doc-1", "brief.pdf", data, config=_config(tmp_path), ai_client=stub)

    assert stub.batch_calls == pdf_service.MAX_BATCH_RETRIES + 1
    assert results[0].status == "success"
    assert results[0].reading_method == "ai_pdf"
    assert results[0].content == "Recovered page 1"
    # Page 2 failed even per-page after retries: falls back to its native
    # (needs_review) result rather than being discarded or fabricated.
    assert results[1].status == "needs_review"
    assert results[1].reading_method == "native_text"
