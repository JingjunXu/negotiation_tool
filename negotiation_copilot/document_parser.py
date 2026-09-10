"""DOCX/TXT/MD/pasted-text parsing into paragraph records, with upload safety
checks (SPEC §4.3). PDF parsing lives in pdf_ingestion.py, but PDFs still pass
through `validate_upload` here first — it is the single safety gate for every
accepted input type.
"""

import hashlib
import io
from pathlib import Path

import docx

from .config import config as default_config
from .config import Config
from .models import ParagraphRecord
from .storage import cache_get, cache_set

ALLOWED_EXTENSIONS = {".pdf", ".docx", ".txt", ".md"}

# Magic-byte prefixes of common executable/binary formats. Checked regardless
# of the claimed extension, since an allowlisted extension does not guarantee
# the bytes actually are that format.
_EXECUTABLE_MAGIC_PREFIXES = (
    b"MZ",  # Windows PE
    b"\x7fELF",  # Linux ELF
    b"\xfe\xed\xfa\xce",  # Mach-O 32-bit
    b"\xfe\xed\xfa\xcf",  # Mach-O 64-bit
    b"\xce\xfa\xed\xfe",  # Mach-O 32-bit, reversed
    b"\xcf\xfa\xed\xfe",  # Mach-O 64-bit, reversed
    b"#!",  # shebang script
)

_ZIP_MAGIC = b"PK\x03\x04"
_PDF_MAGIC = b"%PDF-"


class UploadRejected(ValueError):
    pass


def sha256_of(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _safe_filename(filename: str) -> str:
    if not filename or "\x00" in filename:
        raise UploadRejected(f"Unsafe filename: {filename!r}")
    if "/" in filename or "\\" in filename or ".." in filename:
        raise UploadRejected(f"Unsafe filename: {filename!r}")
    return filename


def validate_upload(
    filename: str,
    data: bytes,
    *,
    config: Config | None = None,
    running_total_bytes: int = 0,
) -> None:
    """Raise UploadRejected if the file fails any §4.3 safety check.

    `running_total_bytes` is the caller's running sum of already-accepted
    material bytes in this session; MAX_UPLOAD_MB is enforced both per file
    and as that running total, since SPEC gives only one size env var.
    """
    cfg = config or default_config
    max_bytes = cfg.max_upload_mb * 1024 * 1024

    safe_name = _safe_filename(filename)
    extension = Path(safe_name).suffix.lower()
    if extension not in ALLOWED_EXTENSIONS:
        raise UploadRejected(f"Unsupported file type: {extension!r}")

    if any(data.startswith(prefix) for prefix in _EXECUTABLE_MAGIC_PREFIXES):
        raise UploadRejected(f"Rejected {safe_name}: content looks like an executable or script, not a document")

    if extension == ".docx" and not data.startswith(_ZIP_MAGIC):
        raise UploadRejected(f"Rejected {safe_name}: does not look like a valid DOCX (zip) file")
    if extension == ".pdf" and not data.startswith(_PDF_MAGIC):
        raise UploadRejected(f"Rejected {safe_name}: does not look like a valid PDF file")
    if extension in {".txt", ".md"}:
        try:
            data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise UploadRejected(f"Rejected {safe_name}: not valid UTF-8 text") from exc

    if len(data) > max_bytes:
        raise UploadRejected(f"Rejected {safe_name}: {len(data)} bytes exceeds MAX_UPLOAD_MB={cfg.max_upload_mb}")
    if running_total_bytes + len(data) > max_bytes:
        raise UploadRejected(
            f"Rejected {safe_name}: adding it would exceed the total upload budget MAX_UPLOAD_MB={cfg.max_upload_mb}"
        )


def _split_paragraphs(text: str) -> list[str]:
    blocks = text.replace("\r\n", "\n").split("\n\n")
    return [block.strip() for block in blocks if block.strip()]


def _read_docx_paragraphs(data: bytes) -> list[str]:
    document = docx.Document(io.BytesIO(data))
    return [p.text.strip() for p in document.paragraphs if p.text.strip()]


def _paragraph_texts(data: bytes, file_type: str) -> list[str]:
    if file_type == "docx":
        return _read_docx_paragraphs(data)
    if file_type in {"txt", "md", "pasted_text"}:
        return _split_paragraphs(data.decode("utf-8"))
    raise ValueError(f"document_parser does not handle file_type={file_type!r}; use pdf_ingestion for PDFs")


def parse_document(
    document_id: str,
    data: bytes,
    file_type: str,
    *,
    app_data_dir: Path | None = None,
) -> list[ParagraphRecord]:
    """Parse DOCX/TXT/MD/pasted text into paragraph records.

    Identical byte content (regardless of `document_id`) reuses the cached
    paragraph texts instead of re-parsing.
    """
    base_dir = app_data_dir if app_data_dir is not None else default_config.app_data_dir
    cache_key = f"{file_type}:{sha256_of(data)}"

    cached = cache_get(base_dir, "parse", cache_key)
    if cached is not None:
        texts = cached
    else:
        texts = _paragraph_texts(data, file_type)
        cache_set(base_dir, "parse", cache_key, texts)

    return [
        ParagraphRecord(document_id=document_id, paragraph_id=f"para-{i + 1}", index=i, text=text)
        for i, text in enumerate(texts)
    ]
