from streamlit.testing.v1 import AppTest

from negotiation_copilot.config import Config
from negotiation_copilot.fake_clients import FakeAIClient
from negotiation_copilot.ingestion_service import ingest_material
from negotiation_copilot.models import NegotiationCase

PAGE_SCRIPT = "from negotiation_copilot.pages import materials\nmaterials.render()\n"


def test_demo_case_shows_info_banner_and_no_upload_yet():
    at = AppTest.from_string(PAGE_SCRIPT)
    at.run(timeout=15)
    assert not at.exception
    assert any("demo case" in info.value for info in at.info)


def test_paste_text_processes_and_appends_document_replacing_demo_case():
    at = AppTest.from_string(PAGE_SCRIPT)
    at.run(timeout=15)
    assert at.session_state["case_is_demo"] is True

    at.text_input(key="materials_paste_label").set_value("shared_case.txt").run(timeout=15)
    at.text_area(key="materials_paste_text").set_value("Both sides agree the deadline is March 1.").run(timeout=15)
    at.button(key="materials_paste_submit").click().run(timeout=15)
    assert not at.exception

    case = at.session_state["case"]
    assert at.session_state["case_is_demo"] is False
    assert len(case.documents) == 1
    assert case.documents[0].filename == "shared_case.txt"
    assert case.documents[0].scope == "shared"
    assert len(case.document_extractions) == 1


def test_paste_text_rejects_empty_text():
    at = AppTest.from_string(PAGE_SCRIPT)
    at.run(timeout=15)

    at.button(key="materials_paste_submit").click().run(timeout=15)
    assert not at.exception
    assert any("Paste some text" in e.value for e in at.error)
    assert at.session_state["case_is_demo"] is True


def test_organize_and_consolidate_replaces_working_case(tmp_path):
    cfg = Config(
        openai_api_key=None, openai_model=None, openai_store_responses=False, run_live_openai_tests=False,
        app_data_dir=tmp_path, max_upload_mb=25, max_pdf_pages=50, log_level="INFO",
    )
    ai_client = FakeAIClient()
    case = NegotiationCase()
    for i, (filename, scope, body) in enumerate([
        ("shared_case.txt", "shared", b"Both sides agree the review ends March 1, 2025."),
        ("private_brief.txt", "my_confidential", b"Internal note: cannot exceed 60 day payment terms."),
    ]):
        record, cues, extraction = ingest_material(
            filename, body, scope, i, config=cfg, ai_client=ai_client,
        )
        case.documents.append(record)
        case.relationship_cues.extend(cues)
        case.document_extractions.append(extraction)

    at = AppTest.from_string(PAGE_SCRIPT)
    at.session_state["case"] = case
    at.session_state["case_is_demo"] = False
    at.run(timeout=15)
    assert not at.exception

    at.button(key="materials_organize_consolidate").click().run(timeout=15)
    assert not at.exception

    new_case = at.session_state["case"]
    assert len(new_case.documents) == 2
    assert new_case.organization is not None
    assert new_case.organization.review_status == "unreviewed"  # never auto-confirmed
