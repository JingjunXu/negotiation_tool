"""Per-document summary + structured extraction (SPEC §7.1-7.2)."""

from .ai_client import AIClient, ExtractionRequest
from .models import DocumentExtraction, TextUnit


def extract_document(
    document_id: str,
    filename: str,
    units: list[TextUnit],
    *,
    ai_client: AIClient,
) -> DocumentExtraction:
    return ai_client.extract_document(ExtractionRequest(document_id=document_id, filename=filename, units=units))
