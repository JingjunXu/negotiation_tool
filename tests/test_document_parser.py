import io

import docx
import pytest

from negotiation_copilot import document_parser
from negotiation_copilot.config import Config


def _config(tmp_path, max_upload_mb=25):
    return Config(
        openai_api_key=None,
        openai_model=None,
        openai_store_responses=False,
        run_live_openai_tests=False,
        app_data_dir=tmp_path,
        max_upload_mb=max_upload_mb,
        max_pdf_pages=50,
        log_level="INFO",
    )


def _docx_bytes(paragraphs: list[str]) -> bytes:
    document = docx.Document()
    for text in paragraphs:
        document.add_paragraph(text)
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def test_parse_txt_paragraphs(tmp_path):
    data = b"First paragraph.\n\nSecond paragraph spans\ntwo lines.\n\n\nThird."
    records = document_parser.parse_document("doc-1", data, "txt", app_data_dir=tmp_path)
    assert [r.text for r in records] == [
        "First paragraph.",
        "Second paragraph spans\ntwo lines.",
        "Third.",
    ]
    assert [r.paragraph_id for r in records] == ["para-1", "para-2", "para-3"]
    assert all(r.document_id == "doc-1" for r in records)


def test_parse_md_paragraphs_same_as_txt(tmp_path):
    data = "# Heading\n\nBody text.".encode("utf-8")
    records = document_parser.parse_document("doc-1", data, "md", app_data_dir=tmp_path)
    assert [r.text for r in records] == ["# Heading", "Body text."]


def test_parse_pasted_text(tmp_path):
    data = "Pasted intent.\n\nSecond thought.".encode("utf-8")
    records = document_parser.parse_document("doc-1", data, "pasted_text", app_data_dir=tmp_path)
    assert [r.text for r in records] == ["Pasted intent.", "Second thought."]


def test_parse_docx(tmp_path):
    data = _docx_bytes(["Role brief", "Confidential instructions", ""])
    records = document_parser.parse_document("doc-1", data, "docx", app_data_dir=tmp_path)
    assert [r.text for r in records] == ["Role brief", "Confidential instructions"]


def test_identical_hash_reuses_parse_result(tmp_path, monkeypatch):
    data = b"Only paragraph."
    document_parser.parse_document("doc-1", data, "txt", app_data_dir=tmp_path)

    def _boom(*args, **kwargs):
        raise AssertionError("should not re-parse identical content")

    monkeypatch.setattr(document_parser, "_paragraph_texts", _boom)
    records = document_parser.parse_document("doc-2", data, "txt", app_data_dir=tmp_path)
    assert [r.text for r in records] == ["Only paragraph."]
    assert all(r.document_id == "doc-2" for r in records)


def test_validate_upload_rejects_oversized(tmp_path):
    cfg = _config(tmp_path, max_upload_mb=1)
    data = b"x" * (2 * 1024 * 1024)
    with pytest.raises(document_parser.UploadRejected):
        document_parser.validate_upload("notes.txt", data, config=cfg)


def test_validate_upload_rejects_total_size(tmp_path):
    cfg = _config(tmp_path, max_upload_mb=1)
    data = b"x" * (600 * 1024)
    with pytest.raises(document_parser.UploadRejected):
        document_parser.validate_upload("notes.txt", data, config=cfg, running_total_bytes=600 * 1024)


def test_validate_upload_rejects_executable_disguised_as_text(tmp_path):
    cfg = _config(tmp_path)
    data = b"MZ" + b"\x00" * 100
    with pytest.raises(document_parser.UploadRejected):
        document_parser.validate_upload("innocuous.txt", data, config=cfg)


def test_validate_upload_rejects_unsupported_extension(tmp_path):
    cfg = _config(tmp_path)
    with pytest.raises(document_parser.UploadRejected):
        document_parser.validate_upload("script.exe", b"MZ\x00\x00", config=cfg)


def test_validate_upload_rejects_path_traversal(tmp_path):
    cfg = _config(tmp_path)
    with pytest.raises(document_parser.UploadRejected):
        document_parser.validate_upload("../../etc/passwd.txt", b"hello", config=cfg)


def test_validate_upload_rejects_invalid_docx(tmp_path):
    cfg = _config(tmp_path)
    with pytest.raises(document_parser.UploadRejected):
        document_parser.validate_upload("fake.docx", b"not a zip", config=cfg)


def test_validate_upload_accepts_good_file(tmp_path):
    cfg = _config(tmp_path)
    document_parser.validate_upload("role_brief.txt", b"Some negotiation content.", config=cfg)
