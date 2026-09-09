from datetime import datetime, timezone

from negotiation_copilot.fixtures import sample_case
from negotiation_copilot.models import NegotiationCase


def test_negotiation_case_round_trip():
    case = sample_case()
    dumped = case.model_dump_json()
    restored = NegotiationCase.model_validate_json(dumped)
    assert restored == case


def test_negotiation_case_round_trip_via_dict():
    case = sample_case()
    restored = NegotiationCase.model_validate(case.model_dump(mode="json"))
    assert restored == case


def test_brief_note_datetime_round_trip():
    from negotiation_copilot.models import BriefNote

    now = datetime.now(timezone.utc)
    note = BriefNote(section_id="sec-1", note_type="my_judgment", text="Looks solid", created_at=now, updated_at=now)
    restored = note.__class__.model_validate_json(note.model_dump_json())
    assert restored == note
