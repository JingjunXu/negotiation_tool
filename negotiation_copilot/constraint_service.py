"""Redlines vs bottomlines (SPEC §8.5). Two different objects — never merged.

`confirmed_by_user` is forced `False` on every AI-produced candidate: "AI
may only propose candidates; confirmed_by_user=True is required before it
enters the Brief's Redlines section or the package validator." Only the
demote/promote/confirm actions in the UI (T5.3) may change it, and even
those never set it True on the user's behalf.
"""

from typing import Literal

from .ai_client import AIClient, ConstraintRequest, reviewed_from_draft_keep_document_ids
from .models import Bottomline, Constraint, NegotiationCase, Redline, WalkAwayAnalysis


def build_constraint_context(case: NegotiationCase) -> str:
    lines: list[str] = []
    for constraint in case.hard_constraints:
        value = constraint.statement.current_value
        if not value:
            continue
        lines.append(f"Constraint [{constraint.source_type}]: {value} [{constraint.statement.evidence_status}]")
    for value in case.authority_limits:
        if value.current_value:
            lines.append(f"Authority limit: {value.current_value} [{value.evidence_status}]")
    for issue in case.issues:
        if issue.target and issue.target.current_value:
            lines.append(f"Issue '{issue.title}' target (not a bottomline candidate on its own): {issue.target.current_value}")
    return "\n".join(lines)


def classify_constraints(
    case: NegotiationCase,
    walk_away: WalkAwayAnalysis | None,
    *,
    ai_client: AIClient,
) -> tuple[list[Redline], list[Bottomline]]:
    has_usable_batna = walk_away is not None and walk_away.estimated_reservation_value is not None
    context = build_constraint_context(case)

    draft = ai_client.classify_constraints(
        ConstraintRequest(context=context, has_batna=has_usable_batna, constraints=case.hard_constraints)
    )

    redlines = [
        Redline(
            statement=reviewed_from_draft_keep_document_ids(r.statement),
            source_type=r.source_type,
            consequence_if_crossed=r.consequence_if_crossed,
            confirmed_by_user=False,
            evidence=r.evidence,
        )
        for r in draft.redline_candidates
    ]

    bottomlines = []
    for b in draft.bottomline_candidates:
        is_really_linked = has_usable_batna and bool(b.linked_batna_reference)
        bottomlines.append(
            Bottomline(
                issue_id=b.issue_id,
                threshold_value=reviewed_from_draft_keep_document_ids(b.threshold_value),
                direction=b.direction,
                rationale=b.rationale,
                linked_batna_reference=b.linked_batna_reference if is_really_linked else None,
                risk_if_crossed=b.risk_if_crossed,
                revisit_conditions=b.revisit_conditions,
                provisional=not is_really_linked,
                confirmed_by_user=False,
                evidence=b.evidence,
            )
        )
    return redlines, bottomlines


def demote_redline_to_bottomline(
    redline: Redline,
    *,
    direction: Literal["min", "max"],
    rationale: str,
    risk_if_crossed: str,
) -> Bottomline:
    """SPEC §8.5: demoting logs the action with ai_original_value preserved
    — passing the same ReviewedText object through (not a copy) guarantees
    that. Confirmation resets: confirming "this is a redline" is not the
    same assertion as confirming "this is a bottomline threshold"."""
    return Bottomline(
        issue_id=None,
        threshold_value=redline.statement,
        direction=direction,
        rationale=rationale,
        linked_batna_reference=None,
        risk_if_crossed=risk_if_crossed,
        revisit_conditions=[],
        provisional=True,
        confirmed_by_user=False,
        evidence=redline.evidence,
    )


def promote_bottomline_to_redline(
    bottomline: Bottomline,
    *,
    source_type: Literal["instructor_rules", "authority_limit", "legal_ethical", "principal_mandate"],
    consequence_if_crossed: str,
) -> Redline:
    return Redline(
        statement=bottomline.threshold_value,
        source_type=source_type,
        consequence_if_crossed=consequence_if_crossed,
        confirmed_by_user=False,
        evidence=bottomline.evidence,
    )
