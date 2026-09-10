"""Option generation — expand the pie (SPEC §8.6). Invention only: this
stage never evaluates, ranks, or rejects. Only the user (or the T5.6
validator) may set `status="rejected"`.
"""

from .ai_client import AIClient, OptionRequest
from .models import InterestItem, NegotiationCase, NegotiationOption


def build_option_context(case: NegotiationCase) -> str:
    lines: list[str] = []
    for issue in case.issues:
        lines.append(f"Issue: {issue.title} (priority={issue.priority}, flexibility={issue.flexibility})")
        if issue.my_position and issue.my_position.current_value:
            lines.append(f"  My position: {issue.my_position.current_value}")
        if issue.counterpart_position and issue.counterpart_position.current_value:
            lines.append(f"  Counterpart position: {issue.counterpart_position.current_value}")
    return "\n".join(lines)


def generate_options(
    case: NegotiationCase,
    interests: list[InterestItem],
    *,
    ai_client: AIClient,
    existing_options: list[NegotiationOption] | None = None,
) -> list[NegotiationOption]:
    """Returns newly generated options only — "Generate more options"
    appends without discarding, so the caller extends its existing list
    with this result rather than replacing it."""
    existing_options = existing_options or []
    known_interest_ids = {i.id for i in interests}

    drafts = ai_client.generate_options(
        OptionRequest(
            context=build_option_context(case),
            interests=interests,
            existing_option_titles=[o.title for o in existing_options],
        )
    )

    options = []
    for draft in drafts:
        my_ids = [iid for iid in draft.serves_my_interest_ids if iid in known_interest_ids]
        their_ids = [iid for iid in draft.serves_their_interest_ids if iid in known_interest_ids]
        if not my_ids and not their_ids:
            continue  # SPEC: "options that serve nobody's interest are a prompt failure" — drop, don't keep
        options.append(
            NegotiationOption(
                title=draft.title,
                description=draft.description,
                option_type=draft.option_type,
                serves_my_interest_ids=my_ids,
                serves_their_interest_ids=their_ids,
                cost_to_me=draft.cost_to_me,
                value_to_them_hypothesis=draft.value_to_them_hypothesis,
                depends_on=draft.depends_on,
                evidence_status=draft.evidence_status,
                status="idea",
            )
        )
    return options
