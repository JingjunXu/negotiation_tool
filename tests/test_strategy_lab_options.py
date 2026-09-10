from streamlit.testing.v1 import AppTest

from negotiation_copilot.fixtures import sample_case

PAGE_SCRIPT = "from negotiation_copilot.pages import strategy_lab\nstrategy_lab.render()\n"


def test_generate_options_appends_without_discarding(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    case = sample_case()
    case.analysis.options = []

    at = AppTest.from_string(PAGE_SCRIPT)
    at.session_state["case"] = case
    at.run(timeout=15)
    assert not at.exception

    at.button(key="generate_options").click().run(timeout=15)
    assert not at.exception
    first_count = len(at.session_state["case"].analysis.options)
    assert first_count >= 8  # fake client breadth (SPEC item 22)

    at.button(key="generate_options").click().run(timeout=15)
    assert not at.exception
    second_count = len(at.session_state["case"].analysis.options)
    assert second_count > first_count  # appended, not replaced


def test_build_haggle_plan_end_to_end_with_fake_client(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    case = sample_case()

    at = AppTest.from_string(PAGE_SCRIPT)
    at.session_state["case"] = case
    at.run(timeout=15)

    at.button(key="build_haggle_plan").click().run(timeout=15)
    assert not at.exception

    plan = at.session_state["case"].analysis.haggle_plan
    assert plan is not None
    assert plan.justification_standard.strip()
    assert plan.anchor.strip()
