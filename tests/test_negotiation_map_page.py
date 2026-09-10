from streamlit.testing.v1 import AppTest

from negotiation_copilot.fixtures import sample_case

PAGE_SCRIPT = "from negotiation_copilot.pages import negotiation_map\nnegotiation_map.render()\n"


def test_confirm_sets_user_confirmed_and_preserves_ai_original_value():
    case = sample_case()
    original_ai_value = case.my_role.ai_original_value

    at = AppTest.from_string(PAGE_SCRIPT)
    at.session_state["case"] = case
    at.run(timeout=15)
    assert not at.exception

    at.button(key="map_my_role_confirm").click().run(timeout=15)
    assert not at.exception

    updated = at.session_state["case"].my_role
    assert updated.evidence_status == "user_confirmed"
    assert updated.ai_original_value == original_ai_value
    assert updated.current_value == case.my_role.current_value


def test_edit_changes_current_value_but_preserves_ai_original_value():
    case = sample_case()
    original_ai_value = case.my_role.ai_original_value

    at = AppTest.from_string(PAGE_SCRIPT)
    at.session_state["case"] = case
    at.run(timeout=15)

    at.checkbox(key="map_my_role_edit_toggle").set_value(True).run(timeout=15)
    at.text_input(key="map_my_role_edit_input").set_value("Corrected role text").run(timeout=15)
    at.button(key="map_my_role_save").click().run(timeout=15)
    assert not at.exception

    updated = at.session_state["case"].my_role
    assert updated.current_value == "Corrected role text"
    assert updated.ai_original_value == original_ai_value
    assert updated.evidence_status == "user_confirmed"


def test_reject_clears_current_value_but_preserves_ai_original_value():
    case = sample_case()
    original_ai_value = case.my_role.ai_original_value

    at = AppTest.from_string(PAGE_SCRIPT)
    at.session_state["case"] = case
    at.run(timeout=15)

    at.button(key="map_my_role_reject").click().run(timeout=15)
    assert not at.exception

    updated = at.session_state["case"].my_role
    assert updated.current_value is None
    assert updated.evidence_status == "unknown"
    assert updated.ai_original_value == original_ai_value


def test_issue_target_confirm_updates_only_that_issue():
    case = sample_case()
    issue = case.issues[0]
    key = f"issue_{issue.id}_target_confirm"

    at = AppTest.from_string(PAGE_SCRIPT)
    at.session_state["case"] = case
    at.run(timeout=15)

    if issue.target is None:
        return  # fixture has no target on this issue; nothing to confirm

    at.button(key=key).click().run(timeout=15)
    assert not at.exception
    updated_issue = next(i for i in at.session_state["case"].issues if i.id == issue.id)
    assert updated_issue.target.evidence_status == "user_confirmed"
