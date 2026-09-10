"""Interests: needs, fears, motives, values (SPEC §8.1).

The hard privacy boundary here — counterpart interests may only be derived
from `shared`/`instructor_rules` materials — is enforced by *excluding*
`my_confidential` content from the counterpart's context bundle before it
ever reaches the AI, not by asking the model nicely not to use it.
"""

from .ai_client import AIClient, InterestRequest, PositionMapRequest, PositionToMap
from .models import InterestItem, NegotiationCase, PositionInterestLink, ReviewedText

_PERMITTED_COUNTERPART_SCOPES = {"shared", "instructor_rules"}


def _permitted_document_ids(case: NegotiationCase, scopes: set[str]) -> set[str]:
    return {doc.document_id for doc in case.documents if doc.scope in scopes}


def _filter_reviewed_text(value: ReviewedText | None, allowed_document_ids: set[str]) -> ReviewedText | None:
    if value is None:
        return None
    kept_evidence = [e for e in value.evidence if e.document_id in allowed_document_ids]
    if not kept_evidence:
        return None
    return value.model_copy(update={"evidence": kept_evidence})


def _format_reviewed(label: str, value: ReviewedText | None) -> str | None:
    if value is None or not value.current_value:
        return None
    lines = [f"{label}: {value.current_value} [{value.evidence_status}]"]
    for e in value.evidence:
        location = f"page {e.page_number}" if e.page_number is not None else (e.paragraph_id or "?")
        lines.append(f"  - ({e.document_id}, {location}): \"{e.excerpt}\"")
    return "\n".join(lines)


def build_interest_context(case: NegotiationCase, *, allowed_document_ids: set[str] | None) -> str:
    """Render the parts of `case` visible to `allowed_document_ids` (None = no
    restriction) as text for the interests prompt.

    Includes `case.interests`/`case.targets` — per-document-extracted, raw
    ("pre-analysis") signal, not yet synthesized into needs/fears/motives/
    values. For negotiations built from many indirect documents (news
    articles, meeting notes, third-party statements) rather than a few
    direct role briefs, this is often where the real evidence for a party's
    interests actually lives — omitting it here starved this stage of
    content that had already been correctly extracted, just filed under a
    different field. See docs/DECISIONS.md.
    """

    def _visible(value: ReviewedText | None) -> ReviewedText | None:
        if allowed_document_ids is None:
            return value
        return _filter_reviewed_text(value, allowed_document_ids)

    lines: list[str] = []
    for label, value in [
        ("My role", case.my_role),
        ("Counterpart role", case.counterpart_role),
        ("Context", case.context),
        ("Objective", case.objective),
        ("BATNA", case.batna),
    ]:
        rendered = _format_reviewed(label, _visible(value))
        if rendered:
            lines.append(rendered)

    for label, values in [
        ("Position", case.positions),
        ("Raw extracted interest (pre-analysis)", case.interests),
        ("Target", case.targets),
        ("Possible concession", case.possible_concessions),
        ("Counterpart information", case.counterpart_information),
        ("Authority limit", case.authority_limits),
    ]:
        for value in values:
            rendered = _format_reviewed(label, _visible(value))
            if rendered:
                lines.append(rendered)

    for issue in case.issues:
        for label, value in [
            (f"Issue '{issue.title}' — my position", issue.my_position),
            (f"Issue '{issue.title}' — counterpart position", issue.counterpart_position),
            (f"Issue '{issue.title}' — target", issue.target),
        ]:
            rendered = _format_reviewed(label, _visible(value))
            if rendered:
                lines.append(rendered)

    return "\n".join(lines)


def analyze_interests(case: NegotiationCase, *, ai_client: AIClient) -> list[InterestItem]:
    my_context = build_interest_context(case, allowed_document_ids=None)
    permitted_ids = _permitted_document_ids(case, _PERMITTED_COUNTERPART_SCOPES)
    counterpart_context = build_interest_context(case, allowed_document_ids=permitted_ids)

    items = ai_client.analyze_interests(
        InterestRequest(
            my_context=my_context,
            counterpart_context=counterpart_context,
            my_hard_constraints=case.hard_constraints,
        )
    )

    result = []
    for item in items:
        is_hypothesis = item.party == "counterpart"
        verification_question = item.verification_question
        if item.statement.evidence_status == "inferred" and not verification_question:
            verification_question = f"Please verify: {item.statement.current_value}?"
        result.append(item.model_copy(update={"is_hypothesis": is_hypothesis, "verification_question": verification_question}))
    return result


def _positions_to_map(case: NegotiationCase) -> list[PositionToMap]:
    """Positions come from `issue.my_position`/`issue.counterpart_position`
    specifically — those are the only party-attributed positions in the
    model (the flat `case.positions` list has no party tag); see
    docs/DECISIONS.md T4.2."""
    positions: list[PositionToMap] = []
    for issue in case.issues:
        if issue.my_position is not None:
            positions.append(PositionToMap(ref=f"issue:{issue.id}:me", party="me", statement=issue.my_position))
        if issue.counterpart_position is not None:
            positions.append(
                PositionToMap(ref=f"issue:{issue.id}:counterpart", party="counterpart", statement=issue.counterpart_position)
            )
    return positions


def map_positions_to_interests(
    case: NegotiationCase,
    interests: list[InterestItem],
    *,
    ai_client: AIClient,
) -> list[PositionInterestLink]:
    positions = _positions_to_map(case)
    if not positions:
        return []

    known_interest_ids = {i.id for i in interests}
    positions_by_ref = {p.ref: p for p in positions}

    drafts = ai_client.map_positions_to_interests(PositionMapRequest(positions=positions, interests=interests))

    links = []
    for draft in drafts:
        position = positions_by_ref.get(draft.ref)
        if position is None:
            continue  # AI referenced a ref we never gave it; ignore rather than trust it
        valid_interest_ids = [iid for iid in draft.underlying_interest_ids if iid in known_interest_ids]
        links.append(
            PositionInterestLink(
                party=position.party,
                stated_position=position.statement,
                underlying_interest_ids=valid_interest_ids,
                inference_basis=draft.inference_basis,
                reframe_question=draft.reframe_question,
                misalignment_note=draft.misalignment_note if position.party == "me" else None,
            )
        )
    return links
