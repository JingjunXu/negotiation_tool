from streamlit.testing.v1 import AppTest

from negotiation_copilot import brief_service
from negotiation_copilot.fake_clients import FakeAIClient
from negotiation_copilot.fixtures import sample_case

PAGE_SCRIPT = "from negotiation_copilot.pages import live_workspace\nlive_workspace.render()\n"


def test_header_shows_walk_away_triggers_and_confirmed_redlines(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    case = sample_case()  # fixture has a confirmed redline and walk-away triggers

    at = AppTest.from_string(PAGE_SCRIPT)
    at.session_state["case"] = case
    at.run(timeout=15)
    assert not at.exception

    warnings_text = " ".join(w.value for w in at.warning) if at.warning else ""
    errors_text = " ".join(e.value for e in at.error) if at.error else ""
    assert "trigger" in warnings_text.lower()
    assert "redline" in errors_text.lower()


def test_mode_a_generates_phrasing_via_fake_client_button_triggered(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    case = sample_case()

    at = AppTest.from_string(PAGE_SCRIPT)
    at.session_state["case"] = case
    at.run(timeout=15)

    # Nothing generated yet — button-triggered only.
    assert "mode_a_variants" not in at.session_state

    at.text_area(key="mode_a_input").set_value("能不能120k成交？").run(timeout=15)
    at.button(key="mode_a_generate").click().run(timeout=15)
    assert not at.exception

    variants = at.session_state["mode_a_variants"]
    assert len(variants) >= 1
    assert len(at.session_state["live_history"]) == 1


def test_clear_history_empties_it(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    case = sample_case()

    at = AppTest.from_string(PAGE_SCRIPT)
    at.session_state["case"] = case
    at.run(timeout=15)

    at.text_area(key="mode_a_input").set_value("能不能120k成交？").run(timeout=15)
    at.button(key="mode_a_generate").click().run(timeout=15)
    assert len(at.session_state["live_history"]) == 1

    at.button(key="clear_live_history").click().run(timeout=15)
    assert at.session_state["live_history"] == []


def test_save_generated_variant_as_note(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    case = sample_case()
    brief = brief_service.generate_brief(case, ai_client=FakeAIClient())

    at = AppTest.from_string(PAGE_SCRIPT)
    at.session_state["case"] = case
    at.session_state["brief"] = brief
    at.run(timeout=15)

    at.text_area(key="mode_a_input").set_value("能不能120k成交？").run(timeout=15)
    at.button(key="mode_a_generate").click().run(timeout=15)

    at.button(key="mode_a_0_save_note").click().run(timeout=15)
    assert not at.exception

    total_notes = sum(len(s.notes) for s in at.session_state["brief"].sections)
    assert total_notes == 1
