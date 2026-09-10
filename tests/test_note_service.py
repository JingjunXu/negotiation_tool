import time

from negotiation_copilot import note_service
from negotiation_copilot.models import BriefSectionState, NegotiationAnalysis, NegotiationCase

CASE_ID = "case-1"


def _section() -> BriefSectionState:
    return BriefSectionState(section_id="objective", title="Objective", ai_generated_base="x")


def test_add_note_appends_with_timestamps(tmp_path):
    section = _section()
    note = note_service.add_note(CASE_ID, section, "my_judgment", "Looks solid", app_data_dir=tmp_path)
    assert section.notes == [note]
    assert note.created_at == note.updated_at
    assert note.text == "Looks solid"


def test_edit_note_updates_text_and_timestamp_not_created_at(tmp_path):
    section = _section()
    note = note_service.add_note(CASE_ID, section, "live_note", "Original", app_data_dir=tmp_path)
    original_created_at = note.created_at
    time.sleep(0.001)
    note_service.edit_note(CASE_ID, section, note.id, "Edited", app_data_dir=tmp_path)
    assert section.notes[0].text == "Edited"
    assert section.notes[0].created_at == original_created_at
    assert section.notes[0].updated_at >= original_created_at


def test_delete_note_removes_it(tmp_path):
    section = _section()
    note = note_service.add_note(CASE_ID, section, "live_note", "x", app_data_dir=tmp_path)
    note_service.delete_note(CASE_ID, section, note.id, app_data_dir=tmp_path)
    assert section.notes == []


def test_set_status_and_pinned(tmp_path):
    section = _section()
    note_service.set_status(CASE_ID, section, "confirmed", app_data_dir=tmp_path)
    note_service.set_pinned(CASE_ID, section, True, app_data_dir=tmp_path)
    assert section.status == "confirmed"
    assert section.pinned is True


# --- SPEC T6.3: notes autosave under APP_DATA_DIR, never browser storage. ---
def test_notes_autosave_and_reload_from_app_data_dir(tmp_path):
    section = _section()
    note_service.add_note(CASE_ID, section, "my_judgment", "Persisted judgment", app_data_dir=tmp_path)

    reloaded = note_service.load_section_state(CASE_ID, section.section_id, app_data_dir=tmp_path)
    assert reloaded is not None
    assert reloaded.notes[0].text == "Persisted judgment"
    # Actually written under the given base dir, not somewhere ad hoc.
    assert (tmp_path / "cases" / CASE_ID / "brief_sections" / "objective.json").exists()


def test_load_section_state_returns_none_when_never_saved(tmp_path):
    assert note_service.load_section_state(CASE_ID, "nonexistent", app_data_dir=tmp_path) is None


# --- SPEC §14.1 item 32: a note never becomes a confirmed fact, constraint,
# or agreement by itself, even when explicitly promoted. ---
def test_promote_to_redline_candidate_is_never_pre_confirmed(tmp_path):
    section = _section()
    note = note_service.add_note(CASE_ID, section, "live_note", "They mentioned a hard 60-day cap", app_data_dir=tmp_path)
    case = NegotiationCase(analysis=NegotiationAnalysis())

    note_service.promote_note_to_case(case, note, "redline_candidate")

    assert len(case.analysis.redlines) == 1
    redline = case.analysis.redlines[0]
    assert redline.confirmed_by_user is False
    assert redline.statement.current_value == "They mentioned a hard 60-day cap"
    assert redline.statement.evidence_status == "user_confirmed"


def test_promote_to_bottomline_candidate_stays_provisional_and_unconfirmed(tmp_path):
    section = _section()
    note = note_service.add_note(CASE_ID, section, "live_note", "Maybe $90k is the real floor", app_data_dir=tmp_path)
    case = NegotiationCase(analysis=NegotiationAnalysis())

    note_service.promote_note_to_case(case, note, "bottomline_candidate")

    bottomline = case.analysis.bottomlines[0]
    assert bottomline.confirmed_by_user is False
    assert bottomline.provisional is True


def test_promote_to_agreement_item_defaults_to_unverified_never_shared(tmp_path):
    section = _section()
    note = note_service.add_note(CASE_ID, section, "live_note", "I think they'll accept this", app_data_dir=tmp_path)
    case = NegotiationCase(analysis=NegotiationAnalysis())

    note_service.promote_note_to_case(case, note, "agreement_item")

    item = case.analysis.agreement_landscape[0]
    assert item.standing == "unverified"
    assert item.verification_question


def test_promote_to_open_question_appends_to_case(tmp_path):
    section = _section()
    note = note_service.add_note(CASE_ID, section, "live_note", "Do they have signing authority?", app_data_dir=tmp_path)
    case = NegotiationCase()

    note_service.promote_note_to_case(case, note, "open_question")

    assert case.open_questions[0].question == "Do they have signing authority?"


def test_promote_initializes_analysis_when_missing(tmp_path):
    section = _section()
    note = note_service.add_note(CASE_ID, section, "live_note", "x", app_data_dir=tmp_path)
    case = NegotiationCase(analysis=None)

    note_service.promote_note_to_case(case, note, "redline_candidate")

    assert case.analysis is not None
    assert len(case.analysis.redlines) == 1
