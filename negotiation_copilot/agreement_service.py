"""Islands of agreement: shared / contested / unverified (SPEC §8.3).

"Shared" is enforced structurally, not just by prompt wording: an item
whose evidence traces only to a `my_confidential` document is downgraded to
"unverified" in code regardless of what the AI proposes, because a claim
only one side can see is one-sided by definition (SPEC §14.1 item 16).
"""

from .ai_client import AgreementRequest, AIClient
from .models import AgreementItem, NegotiationCase, ReviewedText

_SHARED_VISIBLE_SCOPES = {"shared", "instructor_rules"}


def _document_scopes(case: NegotiationCase) -> dict[str, str]:
    return {doc.document_id: doc.scope for doc in case.documents}


def _format_reviewed(label: str, value: ReviewedText | None, scopes: dict[str, str]) -> str | None:
    if value is None or not value.current_value:
        return None
    lines = [f"{label}: {value.current_value} [{value.evidence_status}]"]
    for e in value.evidence:
        scope = scopes.get(e.document_id, "unknown")
        location = f"page {e.page_number}" if e.page_number is not None else (e.paragraph_id or "?")
        lines.append(f"  - ({e.document_id}, scope={scope}, {location}): \"{e.excerpt}\"")
    return "\n".join(lines)


def build_agreement_context(case: NegotiationCase) -> str:
    scopes = _document_scopes(case)
    lines: list[str] = []
    for label, value in [("Context", case.context), ("Objective", case.objective)]:
        rendered = _format_reviewed(label, value, scopes)
        if rendered:
            lines.append(rendered)

    for label, values in [
        ("Position", case.positions),
        ("Counterpart information", case.counterpart_information),
    ]:
        for value in values:
            rendered = _format_reviewed(label, value, scopes)
            if rendered:
                lines.append(rendered)

    for issue in case.issues:
        for label, value in [
            (f"Issue '{issue.title}' — my position", issue.my_position),
            (f"Issue '{issue.title}' — counterpart position", issue.counterpart_position),
            (f"Issue '{issue.title}' — target", issue.target),
        ]:
            rendered = _format_reviewed(label, value, scopes)
            if rendered:
                lines.append(rendered)

    return "\n".join(lines)


def analyze_agreement_landscape(case: NegotiationCase, *, ai_client: AIClient) -> list[AgreementItem]:
    context = build_agreement_context(case)
    known_conflict_ids = {c.id for c in case.conflicts}
    scopes = _document_scopes(case)

    drafts = ai_client.map_agreement_landscape(AgreementRequest(context=context, conflicts=case.conflicts))

    items = []
    for draft in drafts:
        evidence_scopes = {scopes.get(e.document_id) for e in draft.evidence}
        standing = draft.standing
        if standing == "shared" and not (evidence_scopes & _SHARED_VISIBLE_SCOPES):
            standing = "unverified"  # one-sided (my_confidential-only) evidence can never be "shared"

        verification_question = draft.verification_question
        if standing != "shared" and not verification_question:
            verification_question = f"Please verify: {draft.statement}"

        conflict_id = draft.conflict_id if draft.conflict_id in known_conflict_ids else None

        items.append(
            AgreementItem(
                kind=draft.kind,
                statement=draft.statement,
                standing=standing,
                my_view=draft.my_view,
                counterpart_view=draft.counterpart_view,
                conflict_id=conflict_id,
                verification_question=verification_question if standing != "shared" else None,
                evidence=draft.evidence,
            )
        )
    return items
