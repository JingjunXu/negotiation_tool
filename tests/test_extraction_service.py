from negotiation_copilot import extraction_service
from negotiation_copilot.ai_client import ExtractionRequest
from negotiation_copilot.models import DocumentExtraction, DocumentSummary, TextUnit


class _StubAIClient:
    def __init__(self, result: DocumentExtraction):
        self._result = result
        self.last_request: ExtractionRequest | None = None

    def extract_document(self, request: ExtractionRequest) -> DocumentExtraction:
        self.last_request = request
        return self._result


def test_extract_document_delegates_to_client():
    expected = DocumentExtraction(document_id="doc-1", summary=DocumentSummary(bullets=[]))
    stub = _StubAIClient(expected)
    units = [TextUnit(document_id="doc-1", paragraph_id="para-1", text="Some text.")]

    result = extraction_service.extract_document("doc-1", "brief.txt", units, ai_client=stub)

    assert result == expected
    assert stub.last_request.document_id == "doc-1"
    assert stub.last_request.filename == "brief.txt"
    assert stub.last_request.units == units
