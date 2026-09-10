"""Route-agnostic PDF reading (SPEC §5.2 step 5): merges native extraction
with AI re-reads of the pages plain extraction couldn't handle. Callers only
ever see `PDFPageResult`; which route produced each page is just a field.
"""

from pathlib import Path

from .ai_client import AIClient, ReadPDFRequest
from .config import Config
from .config import config as default_config
from .document_parser import sha256_of
from .models import PDFPageResult
from .pdf_ingestion import extract_native_pages
from .storage import cache_get, cache_set

MAX_BATCH_RETRIES = 2
MAX_PER_PAGE_RETRIES = 2


class TooManyPagesError(ValueError):
    pass


def _client_cache_tag(ai_client: AIClient | None) -> str:
    if ai_client is None:
        return "native_only"
    return getattr(ai_client, "cache_tag", type(ai_client).__name__)


def _read_with_retry(ai_client: AIClient, request: ReadPDFRequest) -> list[PDFPageResult]:
    """Retry the batch call; if it keeps failing, degrade to one call per
    page so a single bad page can't take pages the AI could read fine down
    with it (SPEC T2.4: per-page retry, partial-result preservation)."""
    for _ in range(MAX_BATCH_RETRIES + 1):
        try:
            return ai_client.read_pdf(request)
        except Exception:
            continue

    results: list[PDFPageResult] = []
    for page_number in request.page_numbers:
        single_page_request = request.model_copy(update={"page_numbers": [page_number]})
        for _ in range(MAX_PER_PAGE_RETRIES + 1):
            try:
                results.extend(ai_client.read_pdf(single_page_request))
                break
            except Exception:
                continue
        # Every attempt for this page failed: it is simply absent from
        # `results`, and the caller keeps that page's native result instead.
    return results


def read_pdf(
    document_id: str,
    filename: str,
    data: bytes,
    *,
    config: Config,
    ai_client: AIClient | None,
    app_data_dir: Path | None = None,
) -> list[PDFPageResult]:
    """Return one PDFPageResult per page, native where sufficient, AI-read
    where not. `ai_client=None` (fake/no-key mode) leaves insufficient pages
    exactly as native extraction found them, still correctly `needs_review`.
    """
    base_dir = app_data_dir if app_data_dir is not None else default_config.app_data_dir
    cache_key = f"{_client_cache_tag(ai_client)}:{sha256_of(data)}"

    cached = cache_get(base_dir, "pdf_read", cache_key)
    if cached is not None:
        return [PDFPageResult.model_validate(item).model_copy(update={"document_id": document_id}) for item in cached]

    native_results = extract_native_pages(document_id, filename, data, config=config)

    if len(native_results) > config.max_pdf_pages:
        raise TooManyPagesError(
            f"{filename} has {len(native_results)} pages, exceeding MAX_PDF_PAGES={config.max_pdf_pages}"
        )

    pages_needing_review = [r.page_number for r in native_results if r.status != "success"]
    if not pages_needing_review or ai_client is None:
        merged = native_results
    else:
        ai_results = _read_with_retry(
            ai_client,
            ReadPDFRequest(document_id=document_id, filename=filename, data=data, page_numbers=pages_needing_review),
        )
        ai_by_page = {result.page_number: result for result in ai_results}
        merged = [ai_by_page.get(native.page_number, native) for native in native_results]

    cache_set(base_dir, "pdf_read", cache_key, [r.model_dump(mode="json") for r in merged])
    return merged
