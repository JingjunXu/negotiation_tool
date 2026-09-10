from streamlit.testing.v1 import AppTest

from negotiation_copilot.fixtures import sample_case
from negotiation_copilot.models import Bottomline, Redline, ReviewedText

PAGE_SCRIPT = "from negotiation_copilot.pages import strategy_lab\nstrategy_lab.render()\n"


def _reviewed(value: str) -> ReviewedText:
    return ReviewedText(current_value=value, ai_original_value=value, evidence_status="explicit", evidence=[])


def test_confirm_redline_sets_confirmed_by_user():
    case = sample_case()
    case.analysis.redlines = [
        Redline(statement=_reviewed("No terms beyond 60 days"), source_type="principal_mandate", consequence_if_crossed="Void", confirmed_by_user=False)
    ]
    redline_id = case.analysis.redlines[0].id

    at = AppTest.from_string(PAGE_SCRIPT)
    at.session_state["case"] = case
    at.run(timeout=15)
    assert not at.exception

    at.button(key=f"redline_{redline_id}_confirm").click().run(timeout=15)
    assert not at.exception
    assert at.session_state["case"].analysis.redlines[0].confirmed_by_user is True


def test_reject_bottomline_removes_it():
    case = sample_case()
    case.analysis.bottomlines = [
        Bottomline(issue_id=None, threshold_value=_reviewed("$100k"), direction="min", rationale="x", linked_batna_reference=None, risk_if_crossed="y")
    ]
    bottomline_id = case.analysis.bottomlines[0].id

    at = AppTest.from_string(PAGE_SCRIPT)
    at.session_state["case"] = case
    at.run(timeout=15)

    at.button(key=f"bottomline_{bottomline_id}_reject").click().run(timeout=15)
    assert not at.exception
    assert at.session_state["case"].analysis.bottomlines == []


def test_demote_redline_moves_it_to_bottomlines_preserving_ai_original_value():
    case = sample_case()
    statement = _reviewed("No terms beyond 60 days")
    case.analysis.redlines = [Redline(statement=statement, source_type="principal_mandate", consequence_if_crossed="Void")]
    case.analysis.bottomlines = []
    redline_id = case.analysis.redlines[0].id

    at = AppTest.from_string(PAGE_SCRIPT)
    at.session_state["case"] = case
    at.run(timeout=15)

    at.checkbox(key=f"redline_{redline_id}_demote_toggle").set_value(True).run(timeout=15)
    at.text_input(key=f"redline_{redline_id}_rationale").set_value("Actually negotiable").run(timeout=15)
    at.text_input(key=f"redline_{redline_id}_risk").set_value("Cash flow strain").run(timeout=15)
    at.button(key=f"redline_{redline_id}_demote_submit").click().run(timeout=15)
    assert not at.exception

    updated_case = at.session_state["case"]
    assert updated_case.analysis.redlines == []
    assert len(updated_case.analysis.bottomlines) == 1
    assert updated_case.analysis.bottomlines[0].threshold_value.ai_original_value == "No terms beyond 60 days"
    assert updated_case.analysis.bottomlines[0].confirmed_by_user is False
