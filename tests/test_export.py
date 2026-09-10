import json

from negotiation_copilot import brief_service, note_service
from negotiation_copilot.fake_clients import FakeAIClient
from negotiation_copilot.fixtures import sample_case
from negotiation_copilot.models import NegotiationCase


def _brief_with_notes(tmp_path):
    case = sample_case()
    brief = brief_service.generate_brief(case, ai_client=FakeAIClient())
    section = brief.sections[0]
    note_service.add_note(case.case_id, section, "my_judgment", "This looks accurate", app_data_dir=tmp_path)
    note_service.add_note(case.case_id, section, "live_note", "Said this out loud in the room", app_data_dir=tmp_path)
    return case, brief


def test_markdown_includes_judgment_by_default_excludes_live_notes(tmp_path):
    case, brief = _brief_with_notes(tmp_path)
    markdown = brief_service.render_brief_markdown(brief)
    assert "This looks accurate" in markdown
    assert "Said this out loud in the room" not in markdown


def test_markdown_includes_live_notes_when_requested(tmp_path):
    case, brief = _brief_with_notes(tmp_path)
    markdown = brief_service.render_brief_markdown(brief, include_live_notes=True)
    assert "Said this out loud in the room" in markdown


def test_markdown_flags_stale_sections(tmp_path):
    case, brief = _brief_with_notes(tmp_path)
    brief.sections[0].stale = True
    markdown = brief_service.render_brief_markdown(brief)
    assert "STALE" in markdown


# --- SPEC §14.1 item 12: exports contain no API key and no unnecessary full text. ---
def test_case_json_export_is_valid_and_has_no_api_key_like_content(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-should-never-appear-anywhere")
    case = sample_case()
    exported = brief_service.export_case_json(case)

    # Round-trips cleanly.
    restored = NegotiationCase.model_validate_json(exported)
    assert restored.case_id == case.case_id

    assert "sk-should-never-appear-anywhere" not in exported
    assert "openai_api_key" not in exported.lower()


def test_pipeline_trace_export_is_valid_json_with_no_api_key(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-should-never-appear-anywhere")
    case = sample_case()
    trace = brief_service.export_pipeline_trace(case)

    data = json.loads(trace)
    assert "documents" in data
    assert "organization" in data
    assert "sk-should-never-appear-anywhere" not in trace


def test_brief_markdown_export_has_no_api_key(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-should-never-appear-anywhere")
    case, brief = _brief_with_notes(tmp_path)
    markdown = brief_service.render_brief_markdown(brief)
    assert "sk-should-never-appear-anywhere" not in markdown
