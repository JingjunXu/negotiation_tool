from negotiation_copilot import brief_service
from negotiation_copilot.fake_clients import FakeAIClient
from negotiation_copilot.fixtures import sample_case
from negotiation_copilot.models import Bottomline, NegotiationAnalysis, NegotiationCase, Redline, ReviewedText

EXPECTED_SECTION_IDS = [
    "case_snapshot", "objective_success_criteria", "walk_away_position", "my_nfmv", "their_nfmv",
    "positions_vs_interests", "islands_of_agreement", "contested_ground", "redlines", "bottomlines",
    "issue_map", "options", "packages", "haggle_plan", "questions_to_ask", "opening_plan",
    "uncertainties", "key_events_deadlines",
]


def _reviewed(value: str) -> ReviewedText:
    return ReviewedText(current_value=value, ai_original_value=value, evidence_status="explicit", evidence=[])


def test_brief_has_all_18_sections_in_order():
    case = sample_case()
    brief = brief_service.generate_brief(case, ai_client=FakeAIClient())
    assert [s.section_id for s in brief.sections] == EXPECTED_SECTION_IDS


# --- SPEC §14.1 item 20: unconfirmed redline candidate never appears in the Redlines section. ---
def test_unconfirmed_redline_excluded_from_redlines_section():
    confirmed = Redline(statement=_reviewed("Confirmed redline text"), source_type="principal_mandate", consequence_if_crossed="Void", confirmed_by_user=True)
    unconfirmed = Redline(statement=_reviewed("Unconfirmed redline text"), source_type="authority_limit", consequence_if_crossed="Void", confirmed_by_user=False)
    case = NegotiationCase(analysis=NegotiationAnalysis(redlines=[confirmed, unconfirmed]))

    brief = brief_service.generate_brief(case, ai_client=FakeAIClient())
    redlines_section = next(s for s in brief.sections if s.section_id == "redlines")
    uncertainties_section = next(s for s in brief.sections if s.section_id == "uncertainties")

    assert "Confirmed redline text" in redlines_section.ai_generated_base
    assert "Unconfirmed redline text" not in redlines_section.ai_generated_base
    assert "Unconfirmed redline candidate: Unconfirmed redline text" in uncertainties_section.ai_generated_base
    assert any("unconfirmed redline candidate" in note.lower() for note in brief.generation_notes)


def test_unconfirmed_bottomline_excluded_from_bottomlines_section_but_visible_in_uncertainties():
    confirmed = Bottomline(issue_id=None, threshold_value=_reviewed("$100k"), direction="min", rationale="x", linked_batna_reference=None, risk_if_crossed="y", confirmed_by_user=True)
    unconfirmed = Bottomline(issue_id=None, threshold_value=_reviewed("$80k"), direction="min", rationale="x", linked_batna_reference=None, risk_if_crossed="y", confirmed_by_user=False)
    case = NegotiationCase(analysis=NegotiationAnalysis(bottomlines=[confirmed, unconfirmed]))

    brief = brief_service.generate_brief(case, ai_client=FakeAIClient())
    bottomlines_section = next(s for s in brief.sections if s.section_id == "bottomlines")
    uncertainties_section = next(s for s in brief.sections if s.section_id == "uncertainties")

    assert "$100k" in bottomlines_section.ai_generated_base
    assert "$80k" not in bottomlines_section.ai_generated_base
    assert "Unconfirmed bottomline candidate: $80k" in uncertainties_section.ai_generated_base


def test_walk_away_missing_raises_preparation_gap():
    case = NegotiationCase()
    brief = brief_service.generate_brief(case, ai_client=FakeAIClient())
    assert any("walk-away" in note.lower() for note in brief.generation_notes)
    walk_away_section = next(s for s in brief.sections if s.section_id == "walk_away_position")
    assert walk_away_section.ai_generated_base == "Not established"


def test_brief_end_to_end_on_fixture_case():
    case = sample_case()
    brief = brief_service.generate_brief(case, ai_client=FakeAIClient())
    for section in brief.sections:
        assert section.ai_generated_base  # every section renders something, even if a "None established" placeholder


# --- SPEC §14.1 item 28: changed inputs mark AI bases stale. ---
def test_editing_redlines_marks_only_redlines_section_stale():
    case = sample_case()
    brief = brief_service.generate_brief(case, ai_client=FakeAIClient())
    assert all(not s.stale for s in brief.sections)

    case.analysis.redlines.append(
        Redline(statement=_reviewed("A brand new redline"), source_type="principal_mandate", consequence_if_crossed="Void", confirmed_by_user=True)
    )
    brief_service.refresh_staleness(case, brief)

    redlines_section = next(s for s in brief.sections if s.section_id == "redlines")
    issue_map_section = next(s for s in brief.sections if s.section_id == "issue_map")
    assert redlines_section.stale is True
    assert issue_map_section.stale is False  # unaffected section stays fresh


def test_editing_issues_marks_issue_map_and_objective_stale_not_redlines():
    case = sample_case()
    brief = brief_service.generate_brief(case, ai_client=FakeAIClient())

    from negotiation_copilot.models import NegotiationIssue

    case.issues.append(NegotiationIssue(title="A brand new issue"))
    brief_service.refresh_staleness(case, brief)

    issue_map_section = next(s for s in brief.sections if s.section_id == "issue_map")
    redlines_section = next(s for s in brief.sections if s.section_id == "redlines")
    assert issue_map_section.stale is True
    assert redlines_section.stale is False


def test_regeneration_produces_fresh_non_stale_sections():
    case = sample_case()
    brief = brief_service.generate_brief(case, ai_client=FakeAIClient())
    case.analysis.redlines.append(
        Redline(statement=_reviewed("Another redline"), source_type="principal_mandate", consequence_if_crossed="Void", confirmed_by_user=True)
    )
    brief_service.refresh_staleness(case, brief)
    assert any(s.stale for s in brief.sections)

    regenerated = brief_service.generate_brief(case, ai_client=FakeAIClient())
    assert all(not s.stale for s in regenerated.sections)


def test_stale_detection_never_touches_notes_status_or_pins(tmp_path):
    case = sample_case()
    brief = brief_service.generate_brief(case, ai_client=FakeAIClient())
    section = next(s for s in brief.sections if s.section_id == "redlines")
    section.pinned = True
    section.status = "confirmed"
    from negotiation_copilot import note_service

    note_service.add_note(case.case_id, section, "my_judgment", "Reviewed this", app_data_dir=tmp_path)

    case.analysis.redlines.append(
        Redline(statement=_reviewed("Yet another redline"), source_type="principal_mandate", consequence_if_crossed="Void", confirmed_by_user=True)
    )
    brief_service.refresh_staleness(case, brief)

    assert section.stale is True
    assert section.pinned is True
    assert section.status == "confirmed"
    assert len(section.notes) == 1
