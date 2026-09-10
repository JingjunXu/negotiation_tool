import pymupdf as fitz  # used here only to synthesize test fixtures
import pytest

from negotiation_copilot import pdf_ingestion
from negotiation_copilot.config import Config


def _config(tmp_path):
    return Config(
        openai_api_key=None,
        openai_model=None,
        openai_store_responses=False,
        run_live_openai_tests=False,
        app_data_dir=tmp_path,
        max_upload_mb=25,
        max_pdf_pages=50,
        log_level="INFO",
    )


def _pdf_bytes(page_texts: list[str | None]) -> bytes:
    """Build a PDF where each entry becomes one page (None = blank page)."""
    doc = fitz.open()
    for text in page_texts:
        page = doc.new_page()
        if text:
            page.insert_text((72, 72), text, fontsize=11)
    return doc.tobytes()


LONG_PARAGRAPH = (
    "This role brief describes the negotiation context in enough detail to read "
    "as a normal business document, well above any low-density threshold for a page."
)


def test_native_pages_keep_correct_page_numbers(tmp_path):
    data = _pdf_bytes([LONG_PARAGRAPH, LONG_PARAGRAPH, LONG_PARAGRAPH])
    results = pdf_ingestion.extract_native_pages("doc-1", "brief.pdf", data, config=_config(tmp_path))
    assert [r.page_number for r in results] == [1, 2, 3]
    assert all(r.document_id == "doc-1" for r in results)


def test_text_sufficient_pdf_takes_native_path(tmp_path):
    data = _pdf_bytes([LONG_PARAGRAPH])
    [result] = pdf_ingestion.extract_native_pages("doc-1", "brief.pdf", data, config=_config(tmp_path))
    assert result.reading_method == "native_text"
    assert result.status == "success"
    assert result.quality_flags == []
    assert LONG_PARAGRAPH.split(".")[0] in result.content


def test_empty_page_flagged_needs_review(tmp_path):
    data = _pdf_bytes([LONG_PARAGRAPH, None])
    results = pdf_ingestion.extract_native_pages("doc-1", "brief.pdf", data, config=_config(tmp_path))
    assert results[0].status == "success"
    assert results[1].status == "needs_review"
    assert "empty" in results[1].quality_flags


def test_a_failed_page_does_not_discard_other_pages(tmp_path):
    data = _pdf_bytes([None, LONG_PARAGRAPH, None])
    results = pdf_ingestion.extract_native_pages("doc-1", "brief.pdf", data, config=_config(tmp_path))
    assert len(results) == 3
    assert [r.status for r in results] == ["needs_review", "success", "needs_review"]


def test_rejects_invalid_pdf_bytes(tmp_path):
    with pytest.raises(Exception):
        pdf_ingestion.extract_native_pages("doc-1", "brief.pdf", b"not a pdf", config=_config(tmp_path))


def test_assess_sufficiency_flags_low_density():
    is_sufficient, flags = pdf_ingestion.assess_sufficiency("Hi")
    assert is_sufficient is False
    assert "low_density" in flags


def test_assess_sufficiency_flags_replacement_char_garbling():
    garbled_text = "\N{REPLACEMENT CHARACTER}" * 60
    is_sufficient, flags = pdf_ingestion.assess_sufficiency(garbled_text)
    assert is_sufficient is False
    assert "garbled" in flags


def test_assess_sufficiency_flags_control_char_garbling():
    garbled_text = (chr(1) + chr(2) + chr(3)) * 20
    is_sufficient, flags = pdf_ingestion.assess_sufficiency(garbled_text)
    assert is_sufficient is False
    assert "garbled" in flags


def test_assess_sufficiency_does_not_flag_normal_line_breaks_as_garbled():
    text = "\n".join([LONG_PARAGRAPH] * 10)
    is_sufficient, flags = pdf_ingestion.assess_sufficiency(text)
    assert is_sufficient is True
    assert flags == []


def test_assess_sufficiency_accepts_chinese_text():
    text = "这是一份关于本次谈判的详细背景说明,内容足够长,能够体现正常文档的信息密度。"
    is_sufficient, flags = pdf_ingestion.assess_sufficiency(text)
    assert is_sufficient is True
    assert flags == []


def test_assess_sufficiency_detects_table_like_layout():
    text = "\n".join(
        [
            "Item        Qty     Price",
            "Widget      12      $4.00",
            "Gadget      3       $9.00",
            "Gizmo       7       $2.50",
        ]
    )
    is_sufficient, flags = pdf_ingestion.assess_sufficiency(text)
    assert is_sufficient is False
    assert "table_suspected" in flags
