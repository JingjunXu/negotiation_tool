from streamlit.testing.v1 import AppTest

from negotiation_copilot.fixtures import sample_case

PAGE_SCRIPT = "from negotiation_copilot.pages import brief_builder\nbrief_builder.render()\n"


def test_generate_brief_populates_sections(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    case = sample_case()

    at = AppTest.from_string(PAGE_SCRIPT)
    at.session_state["case"] = case
    at.run(timeout=15)
    assert not at.exception

    at.button(key="generate_brief").click().run(timeout=15)
    assert not at.exception

    brief = at.session_state["brief"]
    assert brief is not None
    assert len(brief.sections) == 18


def test_add_note_and_pin_section(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    case = sample_case()

    at = AppTest.from_string(PAGE_SCRIPT)
    at.session_state["case"] = case
    at.run(timeout=15)
    at.button(key="generate_brief").click().run(timeout=15)

    section_id = at.session_state["brief"].sections[0].section_id

    at.checkbox(key=f"section_{section_id}_pin").set_value(True).run(timeout=15)
    assert not at.exception
    assert at.session_state["brief"].sections[0].pinned is True

    at.radio(key=f"section_{section_id}_note_type").set_value("my_judgment").run(timeout=15)
    at.text_area(key=f"section_{section_id}_note_text").set_value("Looks accurate").run(timeout=15)
    at.button(key=f"section_{section_id}_add_note_submit").click().run(timeout=15)
    assert not at.exception

    notes = at.session_state["brief"].sections[0].notes
    assert len(notes) == 1
    assert notes[0].text == "Looks accurate"


def test_regenerate_brief_preserves_notes_and_pins(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    case = sample_case()

    at = AppTest.from_string(PAGE_SCRIPT)
    at.session_state["case"] = case
    at.run(timeout=15)
    at.button(key="generate_brief").click().run(timeout=15)

    section_id = at.session_state["brief"].sections[0].section_id
    at.checkbox(key=f"section_{section_id}_pin").set_value(True).run(timeout=15)
    at.text_area(key=f"section_{section_id}_note_text").set_value("Keep me").run(timeout=15)
    at.button(key=f"section_{section_id}_add_note_submit").click().run(timeout=15)

    # Regenerate — human content must survive (SPEC §10.4).
    at.button(key="generate_brief").click().run(timeout=15)
    assert not at.exception

    regenerated_section = next(s for s in at.session_state["brief"].sections if s.section_id == section_id)
    assert regenerated_section.pinned is True
    assert len(regenerated_section.notes) == 1
    assert regenerated_section.notes[0].text == "Keep me"
