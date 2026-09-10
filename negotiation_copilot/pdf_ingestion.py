"""Native per-page PDF text extraction with a sufficiency heuristic (SPEC §5.2-§5.3).

Downstream (T2.3) routes pages this module marks `needs_review` to AI reading;
this module never invents content for a page it cannot read cleanly.
"""

import io
import re
import unicodedata

import pypdf

from .config import Config
from .document_parser import validate_upload
from .models import PDFPageResult

_COLUMN_GAP_RE = re.compile(r"  +")

# Control, private-use, surrogate, unassigned. Private-use codepoints in
# particular are the classic symptom of a PDF whose embedded font remaps
# glyphs without a usable ToUnicode map — real garbling, not a language
# issue. Deliberately category-based rather than an ASCII whitelist so
# legitimate non-Latin text (this app is bilingual ZH<->EN) is never flagged.
_BAD_UNICODE_CATEGORIES = {"Cc", "Co", "Cs", "Cn"}
_REPLACEMENT_CHAR = "�"

_LOW_DENSITY_WEIGHT_THRESHOLD = 40
_GARBLED_BAD_CHAR_RATIO = 0.1
_TABLE_LINE_FRACTION = 0.25

# CJK ideographs and syllabaries pack far more meaning per character than
# Latin script (roughly one CJK character per one-to-two English words), so a
# flat character-count threshold would flag ordinary Chinese text as
# low-density. Weight CJK characters higher instead of using a raw length.
_CJK_RANGES = (
    (0x4E00, 0x9FFF),  # CJK Unified Ideographs
    (0x3400, 0x4DBF),  # CJK Extension A
    (0xF900, 0xFAFF),  # CJK Compatibility Ideographs
    (0x3040, 0x30FF),  # Hiragana + Katakana
    (0xAC00, 0xD7A3),  # Hangul syllables
)


def _is_cjk(ch: str) -> bool:
    code = ord(ch)
    return any(lo <= code <= hi for lo, hi in _CJK_RANGES)


def _content_weight(text: str) -> float:
    return sum(2.0 if _is_cjk(ch) else 1.0 for ch in text if not ch.isspace())


def _bad_char_ratio(text: str) -> float:
    # Whitespace control characters (newline, tab, CR, form feed) are normal
    # line-break/formatting artifacts of PDF text extraction, not garbling.
    non_whitespace = [ch for ch in text if not ch.isspace()]
    if not non_whitespace:
        return 0.0
    bad = sum(1 for ch in non_whitespace if ch == _REPLACEMENT_CHAR or unicodedata.category(ch) in _BAD_UNICODE_CATEGORIES)
    return bad / len(non_whitespace)


def assess_sufficiency(text: str) -> tuple[bool, list[str]]:
    """Return (is_sufficient, quality_flags) for one page's extracted text.

    Flags mirror SPEC §5.2's four sufficiency checks: empty pages, garbled
    text, low text density, and table-suspicious layout (a proxy for
    "missing tables" — plain text extraction cannot tell whether a table's
    structure survived, only that the layout looks columnar).
    """
    stripped = text.strip()
    if not stripped:
        return False, ["empty"]

    flags: list[str] = []

    if _bad_char_ratio(stripped) > _GARBLED_BAD_CHAR_RATIO:
        flags.append("garbled")

    if _content_weight(stripped) < _LOW_DENSITY_WEIGHT_THRESHOLD:
        flags.append("low_density")

    lines = [line for line in stripped.splitlines() if line.strip()]
    if lines:
        column_like_lines = sum(1 for line in lines if _COLUMN_GAP_RE.search(line))
        if column_like_lines / len(lines) >= _TABLE_LINE_FRACTION:
            flags.append("table_suspected")

    is_sufficient = not flags
    return is_sufficient, flags


def extract_native_pages(
    document_id: str,
    filename: str,
    data: bytes,
    *,
    config: Config | None = None,
) -> list[PDFPageResult]:
    """Extract native text per page, 1-based page numbers, sufficiency-flagged."""
    validate_upload(filename, data, config=config)

    reader = pypdf.PdfReader(io.BytesIO(data))
    results: list[PDFPageResult] = []
    for index, page in enumerate(reader.pages):
        page_number = index + 1
        text = page.extract_text() or ""
        is_sufficient, flags = assess_sufficiency(text)
        results.append(
            PDFPageResult(
                document_id=document_id,
                page_number=page_number,
                reading_method="native_text",
                content=text,
                key_items=[],
                quality_flags=flags,
                status="success" if is_sufficient else "needs_review",
            )
        )
    return results
