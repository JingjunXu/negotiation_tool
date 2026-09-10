"""Walk-away analysis: BATNA -> reservation value -> triggers -> exit script
(SPEC §8.4). Runs before constraint classification, since bottomlines are
derived from this.
"""

from .ai_client import (
    AIClient,
    WalkAwayRequest,
    reviewed_from_draft_keep_document_ids,
)
from .models import NegotiationCase, ReviewedText, WalkAwayAnalysis


def _format_reviewed(label: str, value: ReviewedText | None) -> str | None:
    if value is None or not value.current_value:
        return None
    return f"{label}: {value.current_value} [{value.evidence_status}]"


def build_walkaway_context(case: NegotiationCase) -> str:
    lines: list[str] = []
    for label, value in [
        ("My role", case.my_role),
        ("Context", case.context),
        ("Objective", case.objective),
        ("BATNA (as extracted)", case.batna),
    ]:
        rendered = _format_reviewed(label, value)
        if rendered:
            lines.append(rendered)
    for label, values in [("Target", case.targets), ("Counterpart information", case.counterpart_information)]:
        for value in values:
            rendered = _format_reviewed(label, value)
            if rendered:
                lines.append(rendered)
    for issue in case.issues:
        rendered = _format_reviewed(f"Issue '{issue.title}' — target", issue.target)
        if rendered:
            lines.append(rendered)
    return "\n".join(lines)


def analyze_walk_away(case: NegotiationCase, *, ai_client: AIClient) -> tuple[WalkAwayAnalysis, list[str]]:
    """Returns (analysis, preparation_gap_warnings) — the caller decides
    where to surface the warnings (e.g. `case.warnings`), keeping this
    function a pure computation like the other analysis-layer services.
    """
    context = build_walkaway_context(case)
    draft = ai_client.analyze_walk_away(WalkAwayRequest(context=context))

    warnings: list[str] = []
    reservation_value = reviewed_from_draft_keep_document_ids(draft.estimated_reservation_value)
    reservation_derivation = draft.reservation_derivation

    if draft.batna_quality == "unknown":
        if reservation_value is not None:
            warnings.append(
                "Preparation gap: BATNA quality is unknown, so the proposed reservation value was discarded."
            )
        reservation_value = None
        reservation_derivation = None
        warnings.append("Preparation gap: BATNA quality is unknown, so no reservation value could be estimated.")
    elif reservation_value is not None:
        aspiration_values = {
            t.current_value for t in case.targets if t.current_value
        } | {i.target.current_value for i in case.issues if i.target is not None and i.target.current_value}
        if reservation_value.current_value in aspiration_values:
            warnings.append(
                "Preparation gap: the proposed reservation value matched a stated target/aspiration and was "
                "discarded — a reservation value must be derived from the BATNA, not from what we're asking for."
            )
            reservation_value = None
            reservation_derivation = None

    analysis = WalkAwayAnalysis(
        my_batna=reviewed_from_draft_keep_document_ids(draft.my_batna) or ReviewedText(),
        batna_quality=draft.batna_quality,
        quality_rationale=draft.quality_rationale,
        actions_to_improve_batna=draft.actions_to_improve_batna,
        estimated_reservation_value=reservation_value,
        reservation_derivation=reservation_derivation,
        counterpart_batna_hypothesis=reviewed_from_draft_keep_document_ids(draft.counterpart_batna_hypothesis),
        tests_to_probe_their_batna=draft.tests_to_probe_their_batna,
        walk_away_triggers=draft.walk_away_triggers,
        exit_script=draft.exit_script,
        do_not_disclose=draft.do_not_disclose,
    )
    return analysis, warnings
