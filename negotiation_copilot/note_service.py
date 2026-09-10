"""Per-section judgment and live notes (SPEC §10.4). Notes are stored
separately from AI content, autosaved under APP_DATA_DIR (never browser
storage), and promoting one to the case (SPEC §10.4, §14.1 item 32) never
bypasses the case's normal confirmation gates — a promoted note becomes a
*candidate* wherever the target type has one (redlines, bottomlines),
never an already-confirmed fact, constraint, or agreement.
"""

from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from .config import config as default_config
from .models import (
    AgreementItem,
    BriefNote,
    BriefSectionState,
    Bottomline,
    NegotiationAnalysis,
    NegotiationCase,
    OpenQuestion,
    Redline,
    ReviewedText,
)

PromotionTarget = Literal["redline_candidate", "bottomline_candidate", "open_question", "agreement_item"]


def _section_path(case_id: str, section_id: str, app_data_dir: Path | None) -> Path:
    base_dir = app_data_dir if app_data_dir is not None else default_config.app_data_dir
    return base_dir / "cases" / case_id / "brief_sections" / f"{section_id}.json"


def autosave_section(case_id: str, section: BriefSectionState, *, app_data_dir: Path | None = None) -> None:
    path = _section_path(case_id, section.section_id, app_data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(section.model_dump_json())


def load_section_state(case_id: str, section_id: str, *, app_data_dir: Path | None = None) -> BriefSectionState | None:
    path = _section_path(case_id, section_id, app_data_dir)
    if not path.exists():
        return None
    return BriefSectionState.model_validate_json(path.read_text())


def add_note(
    case_id: str,
    section: BriefSectionState,
    note_type: Literal["my_judgment", "live_note"],
    text: str,
    *,
    app_data_dir: Path | None = None,
) -> BriefNote:
    now = datetime.now(timezone.utc)
    note = BriefNote(section_id=section.section_id, note_type=note_type, text=text, created_at=now, updated_at=now)
    section.notes.append(note)
    autosave_section(case_id, section, app_data_dir=app_data_dir)
    return note


def edit_note(case_id: str, section: BriefSectionState, note_id: str, new_text: str, *, app_data_dir: Path | None = None) -> None:
    for note in section.notes:
        if note.id == note_id:
            note.text = new_text
            note.updated_at = datetime.now(timezone.utc)
            autosave_section(case_id, section, app_data_dir=app_data_dir)
            return


def delete_note(case_id: str, section: BriefSectionState, note_id: str, *, app_data_dir: Path | None = None) -> None:
    section.notes = [n for n in section.notes if n.id != note_id]
    autosave_section(case_id, section, app_data_dir=app_data_dir)


def set_status(
    case_id: str,
    section: BriefSectionState,
    status: Literal["confirmed", "tentative", "needs_verification", "no_longer_relevant"],
    *,
    app_data_dir: Path | None = None,
) -> None:
    section.status = status
    autosave_section(case_id, section, app_data_dir=app_data_dir)


def set_pinned(case_id: str, section: BriefSectionState, pinned: bool, *, app_data_dir: Path | None = None) -> None:
    section.pinned = pinned
    autosave_section(case_id, section, app_data_dir=app_data_dir)


def promote_note_to_case(
    case: NegotiationCase,
    note: BriefNote,
    target: PromotionTarget,
) -> None:
    """SPEC item 32: a note never becomes a confirmed fact, constraint, or
    agreement by itself — every promotion target that has a confirmation
    gate (redlines, bottomlines) is created unconfirmed; agreement items
    are created at the least-committal standing ("unverified")."""
    analysis = case.analysis
    if analysis is None:
        analysis = NegotiationAnalysis()
        case.analysis = analysis

    statement = ReviewedText(current_value=note.text, ai_original_value=None, evidence_status="user_confirmed")

    if target == "redline_candidate":
        analysis.redlines.append(
            Redline(
                statement=statement,
                source_type="principal_mandate",
                consequence_if_crossed="Not established — promoted from a live note",
                confirmed_by_user=False,
            )
        )
    elif target == "bottomline_candidate":
        analysis.bottomlines.append(
            Bottomline(
                issue_id=None,
                threshold_value=statement,
                direction="min",
                rationale="Promoted from a live note",
                linked_batna_reference=None,
                risk_if_crossed="Not established — promoted from a live note",
                provisional=True,
                confirmed_by_user=False,
            )
        )
    elif target == "open_question":
        case.open_questions.append(OpenQuestion(question=note.text))
    elif target == "agreement_item":
        analysis.agreement_landscape.append(
            AgreementItem(kind="fact", statement=note.text, standing="unverified", verification_question=f"Please verify: {note.text}")
        )
    else:  # pragma: no cover - exhaustive Literal
        raise ValueError(f"Unknown promotion target: {target!r}")
