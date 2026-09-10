"""Language assistant (SPEC §11): Chinese intent -> negotiation English
(§11.1), counterpart statement -> bilingual reply (§11.2), and risk-flag
checking (§11.3). The AI self-reports some flags, but every draft is also
checked by deterministic code against the case's confirmed limits — the
same "never trust the model alone for a safety-relevant flag" pattern used
for redlines (T5.2) and organization confirmation (T3.2). This is what
actually guarantees BATNA/reservation value/bottomline/redline rationale
never leak into a draft.
"""

import re

from .ai_client import (
    AIClient,
    BilingualReplyRequest,
    PhraseInEnglishRequest,
)
from .models import (
    BilingualReplyDraft,
    EnglishPhraseVariant,
    LanguageDraftRequest,
    NegotiationCase,
)
from .package_service import extract_number

_NUMBER_RE = re.compile(r"\d[\d,]*(?:\.\d+)?%?")
_CJK_RE = re.compile(r"[一-鿿]")
_COMMITMENT_PHRASES = ("we will", "we agree to", "we commit to", "guaranteed", "we promise", "i will", "i agree to")
_CONDITIONAL_MARKERS = ("if ", "provided that", "in exchange", "only if", "as long as", "assuming")

# Never let these into the language-assistant context, selected or not —
# quoting them into what the model sees is itself a disclosure risk, even
# with an instruction not to repeat them (SPEC §11.3 / CLAUDE.md "Never
# disclose BATNA, reservation value, bottomline, or redline rationale").
_EXCLUDED_SECTION_IDS = {"walk_away_position", "redlines", "bottomlines"}


def _numbers_in(text: str) -> set[str]:
    return set(_NUMBER_RE.findall(text or ""))


def build_language_context(request: LanguageDraftRequest, case: NegotiationCase, brief=None) -> str:
    """Only ever includes confirmed context: the case's context/objective,
    plus any user-selected Brief sections — with the private sections
    (walk-away, redlines, bottomlines) excluded unconditionally."""
    lines: list[str] = []
    if case.context and case.context.current_value:
        lines.append(f"Context: {case.context.current_value}")
    if case.objective and case.objective.current_value:
        lines.append(f"Objective: {case.objective.current_value}")

    if brief is not None:
        selected_ids = set(request.selected_brief_section_ids) - _EXCLUDED_SECTION_IDS
        for section in brief.sections:
            if section.section_id in selected_ids:
                lines.append(f"{section.title}: {section.ai_generated_base}")

    return "\n".join(lines)


def check_risk_flags(
    draft_texts: list[str],
    original_input: str,
    case: NegotiationCase,
    extra_do_not_disclose: list[str],
) -> list[str]:
    """Pure function, no AI (SPEC §11.3 risk flag set). Never trusts the
    model's self-reported flags alone."""
    flags: set[str] = set()
    combined = " ".join(t for t in draft_texts if t)
    combined_lower = combined.lower()
    analysis = case.analysis

    if analysis and analysis.walk_away:
        wa = analysis.walk_away
        if wa.my_batna.current_value and wa.my_batna.current_value.lower() in combined_lower:
            flags.add("reveals_batna")
        if wa.estimated_reservation_value and wa.estimated_reservation_value.current_value and (
            wa.estimated_reservation_value.current_value.lower() in combined_lower
        ):
            flags.add("reveals_reservation_value")

    for bottomline in (analysis.bottomlines if analysis else []):
        if not bottomline.confirmed_by_user:
            continue
        if bottomline.threshold_value.current_value and bottomline.threshold_value.current_value.lower() in combined_lower:
            flags.add("reveals_bottomline")
        threshold = extract_number(bottomline.threshold_value.current_value)
        if threshold is not None:
            for number_str in _numbers_in(combined) - _numbers_in(original_input):
                value = extract_number(number_str)
                if value is None:
                    continue
                crossed = (bottomline.direction == "min" and value < threshold) or (
                    bottomline.direction == "max" and value > threshold
                )
                if crossed:
                    flags.add("contradicts_confirmed_field")

    for redline in (analysis.redlines if analysis else []):
        if redline.confirmed_by_user and redline.statement.current_value and redline.statement.current_value.lower() in combined_lower:
            flags.add("crosses_redline")

    for item in (analysis.agreement_landscape if analysis else []):
        if item.standing in ("contested", "unverified") and item.statement and item.statement.lower() in combined_lower:
            flags.add("asserts_contested_fact_as_agreed")

    for term in extra_do_not_disclose:
        if term and term.lower() in combined_lower:
            flags.add("reveals_bottomline")

    new_numbers = _numbers_in(combined) - _numbers_in(original_input)
    if new_numbers:
        flags.add("new_commitment")
        if not any(marker in combined_lower for marker in _CONDITIONAL_MARKERS):
            flags.add("unconditional_concession")

    # Comparing English commitment phrases against the original only makes
    # sense when the original is itself in a Latin script — a Chinese
    # original can never contain "we will", so that comparison would flag
    # every faithful ZH->EN translation as a "new" commitment. Skip it
    # whenever the original contains CJK text; the numeric diff above
    # already catches new commitments across languages.
    if not _CJK_RE.search(original_input):
        original_lower = original_input.lower()
        if any(p in combined_lower for p in _COMMITMENT_PHRASES) and not any(p in original_lower for p in _COMMITMENT_PHRASES):
            flags.add("new_commitment")

    return sorted(flags)


def phrase_in_english(
    request: LanguageDraftRequest,
    case: NegotiationCase,
    *,
    ai_client: AIClient,
    brief=None,
) -> list[EnglishPhraseVariant]:
    context = build_language_context(request, case, brief)
    drafts = ai_client.phrase_in_english(PhraseInEnglishRequest(draft_request=request, context=context))

    variants = []
    for draft in drafts[:3]:
        checked_flags = check_risk_flags(
            [draft.english_draft, draft.chinese_back_translation], request.user_input, case, request.do_not_disclose
        )
        variants.append(
            EnglishPhraseVariant(
                label=draft.label,
                english_draft=draft.english_draft,
                chinese_back_translation=draft.chinese_back_translation,
                risk_flags=sorted(set(draft.risk_flags) | set(checked_flags)),
            )
        )
    return variants


def draft_bilingual_reply(
    request: LanguageDraftRequest,
    case: NegotiationCase,
    *,
    ai_client: AIClient,
    brief=None,
) -> BilingualReplyDraft:
    context = build_language_context(request, case, brief)
    draft = ai_client.draft_bilingual_reply(BilingualReplyRequest(draft_request=request, context=context))

    checked_flags = check_risk_flags(
        [draft.english_draft, draft.chinese_draft], request.user_input, case, request.do_not_disclose
    )
    return BilingualReplyDraft(
        counterpart_summary_zh=draft.counterpart_summary_zh,
        counterpart_summary_en=draft.counterpart_summary_en,
        points_to_verify=draft.points_to_verify,
        chinese_draft=draft.chinese_draft,
        english_draft=draft.english_draft,
        risk_flags=sorted(set(draft.risk_flags) | set(checked_flags)),
    )
