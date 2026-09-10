from streamlit.testing.v1 import AppTest

from negotiation_copilot.fixtures import sample_case
from negotiation_copilot.models import Constraint, ReviewedText

PAGE_SCRIPT = "from negotiation_copilot.pages import strategy_lab\nstrategy_lab.render()\n"


def test_run_interest_analysis_populates_interests_via_fake_client(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    case = sample_case()
    case.hard_constraints = [
        Constraint(
            statement=ReviewedText(current_value="Cannot exceed 60 day terms", ai_original_value="Cannot exceed 60 day terms", evidence_status="explicit"),
            source_type="principal_mandate",
        )
    ]
    case.analysis.interests = []
    case.analysis.position_links = []

    at = AppTest.from_string(PAGE_SCRIPT)
    at.session_state["case"] = case
    at.run(timeout=15)
    assert not at.exception

    at.button(key="run_interests").click().run(timeout=15)
    assert not at.exception

    updated = at.session_state["case"].analysis
    assert len(updated.interests) == 1
    assert updated.interests[0].party == "me"
    assert updated.interests[0].category == "need"


def test_run_agreement_analysis_populates_landscape_via_fake_client(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    case = sample_case()
    case.analysis.agreement_landscape = []

    at = AppTest.from_string(PAGE_SCRIPT)
    at.session_state["case"] = case
    at.run(timeout=15)
    assert not at.exception

    at.button(key="run_agreement").click().run(timeout=15)
    assert not at.exception

    updated = at.session_state["case"].analysis.agreement_landscape
    # the fixture case has one Conflict, so the fake client should surface it as contested
    assert any(item.standing == "contested" for item in updated)


def test_strategy_lab_works_when_case_has_no_analysis_yet(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    case = sample_case()
    case.analysis = None

    at = AppTest.from_string(PAGE_SCRIPT)
    at.session_state["case"] = case
    at.run(timeout=15)
    assert not at.exception
    assert at.session_state["case"].analysis is not None
