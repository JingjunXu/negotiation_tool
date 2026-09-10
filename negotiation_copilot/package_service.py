"""Packages and haggle prep (SPEC §8.7), plus the limit validator (SPEC
§8.7 / T5.6). The validator is plain code — no AI — and is called both
while building the concession ladder (to stop it before crossing a
confirmed limit) and to annotate the finished packages.
"""

import re
from typing import Literal

from .ai_client import AIClient, HaggleRequest
from .models import (
    Bottomline,
    ConcessionStep,
    HagglePlan,
    InterestItem,
    NegotiationCase,
    NegotiationOption,
    Redline,
    TradeCurrency,
    TradePackage,
)

_NUMBER_RE = re.compile(r"[-+]?\d[\d,]*(?:\.\d+)?")
_MAX_KEYWORDS = ("beyond", "more than", "over ", "exceed", "above", "greater than")
_MIN_KEYWORDS = ("under", "less than", "below", "at least", "minimum")


def extract_number(text: str | None) -> float | None:
    if not text:
        return None
    match = _NUMBER_RE.search(text)
    if not match:
        return None
    return float(match.group(0).replace(",", ""))


def _infer_direction(text: str | None) -> Literal["min", "max"] | None:
    lowered = (text or "").lower()
    if any(k in lowered for k in _MAX_KEYWORDS):
        return "max"
    if any(k in lowered for k in _MIN_KEYWORDS):
        return "min"
    return None


def _text_crosses_redline(text: str, redline: Redline) -> bool:
    redline_number = extract_number(redline.statement.current_value)
    direction = _infer_direction(redline.statement.current_value)
    text_number = extract_number(text)
    if redline_number is None or direction is None or text_number is None:
        return False  # cannot verify -> no false positive
    if direction == "max":
        return text_number > redline_number
    return text_number < redline_number


def _validate_package(package: TradePackage, redlines: list[Redline]) -> list[str]:
    warnings = []
    for text in [*package.what_i_give, *package.what_i_get, package.label]:
        for redline in redlines:
            if _text_crosses_redline(text, redline):
                warnings.append(
                    f"violates_redline: '{text}' in package '{package.label}' conflicts with confirmed "
                    f"redline '{redline.statement.current_value}'"
                )
    return warnings


def _validate_ladder(steps: list[ConcessionStep], redlines: list[Redline], bottomlines: list[Bottomline]) -> list[str]:
    warnings = []
    for step in steps:
        step_value = extract_number(step.to_value)
        for bottomline in bottomlines:
            if bottomline.issue_id and step.issue_id and bottomline.issue_id != step.issue_id:
                continue
            threshold = extract_number(bottomline.threshold_value.current_value)
            if step_value is None or threshold is None:
                continue
            crossed = (bottomline.direction == "min" and step_value < threshold) or (
                bottomline.direction == "max" and step_value > threshold
            )
            if crossed:
                warnings.append(
                    f"crosses_bottomline: step {step.order} ({step.to_value}) crosses confirmed bottomline {threshold}"
                )
        for redline in redlines:
            if _text_crosses_redline(step.to_value, redline):
                warnings.append(
                    f"violates_redline: step {step.order} ({step.to_value}) conflicts with confirmed "
                    f"redline '{redline.statement.current_value}'"
                )
    return warnings


def validate_against_limits(
    target: TradePackage | list[ConcessionStep],
    redlines: list[Redline],
    bottomlines: list[Bottomline],
) -> list[str]:
    """Pure function, no AI (SPEC T5.6). Checks a package or a concession
    ladder against CONFIRMED redlines/bottomlines only — SPEC: nothing
    unconfirmed by the user is ever a hard limit."""
    confirmed_redlines = [r for r in redlines if r.confirmed_by_user]
    confirmed_bottomlines = [b for b in bottomlines if b.confirmed_by_user]

    if isinstance(target, TradePackage):
        return _validate_package(target, confirmed_redlines)
    return _validate_ladder(target, confirmed_redlines, confirmed_bottomlines)


def compute_trade_currencies(options: list[NegotiationOption], interests: list[InterestItem]) -> list[TradeCurrency]:
    """Mechanical, code-only derivation (SPEC §8.7: "derived from option
    costs and interest matches") — no AI judgment needed for this table."""
    give_side = [
        TradeCurrency(item=o.title, cost_to_me=o.cost_to_me, value_to_them_hypothesis=o.value_to_them_hypothesis, direction="i_can_give")
        for o in options
        if o.cost_to_me in ("low", "medium")
    ]
    get_side = [
        TradeCurrency(item=i.statement.current_value, cost_to_me="unknown", value_to_them_hypothesis="unknown", direction="i_want_to_get")
        for i in interests
        if i.party == "me" and i.statement.current_value
    ]
    return give_side + get_side


def build_haggle_context(case: NegotiationCase) -> str:
    lines = []
    for issue in case.issues:
        lines.append(f"Issue: {issue.title} (id={issue.id}, priority={issue.priority}, flexibility={issue.flexibility})")
    return "\n".join(lines)


def _build_validated_ladder(
    step_drafts,
    redlines: list[Redline],
    bottomlines: list[Bottomline],
) -> list[ConcessionStep]:
    steps: list[ConcessionStep] = []
    previous_delta: float | None = None
    for draft in step_drafts:
        if not draft.ask_in_return or not draft.ask_in_return.strip():
            continue  # never construct an unconditional (invalid) step
        step = ConcessionStep(
            order=len(steps) + 1,
            issue_id=draft.issue_id,
            from_value=draft.from_value,
            to_value=draft.to_value,
            ask_in_return=draft.ask_in_return,
            trigger_condition=draft.trigger_condition,
        )

        if validate_against_limits([step], redlines, bottomlines):
            break  # SPEC: the ladder must never reach a redline or a confirmed bottomline

        from_num, to_num = extract_number(step.from_value), extract_number(step.to_value)
        if from_num is not None and to_num is not None:
            delta = abs(from_num - to_num)
            if previous_delta is not None and delta > previous_delta:
                break  # increments must shrink, never grow, as the ladder descends
            previous_delta = delta

        steps.append(step)
    return steps


def build_haggle_plan(
    case: NegotiationCase,
    options: list[NegotiationOption],
    interests: list[InterestItem],
    redlines: list[Redline],
    bottomlines: list[Bottomline],
    *,
    ai_client: AIClient,
) -> HagglePlan:
    trade_currencies = compute_trade_currencies(options, interests)
    draft = ai_client.build_haggle_plan(
        HaggleRequest(context=build_haggle_context(case), options=options, trade_currencies=trade_currencies)
    )

    if not draft.justification_standard or not draft.justification_standard.strip():
        raise ValueError("AI failed to provide a justification standard for the anchor — an anchor without one is invalid")

    known_option_ids = {o.id for o in options}
    packages = []
    for p in draft.packages:
        package = TradePackage(
            label=p.label,
            option_ids=[oid for oid in p.option_ids if oid in known_option_ids],
            what_i_give=p.what_i_give,
            what_i_get=p.what_i_get,
            equivalence_note=p.equivalence_note,
        )
        package.validator_warnings = validate_against_limits(package, redlines, bottomlines)
        packages.append(package)

    ladder = _build_validated_ladder(draft.concession_ladder, redlines, bottomlines)

    return HagglePlan(
        anchor=draft.anchor,
        justification_standard=draft.justification_standard,
        trade_currencies=trade_currencies,
        packages=packages,
        concession_ladder=ladder,
        counter_tactics=draft.counter_tactics,
        validator_warnings=validate_against_limits(ladder, redlines, bottomlines),
    )
