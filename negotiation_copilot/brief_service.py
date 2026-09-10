"""Living Brief assembly (SPEC §10.2): 18 sections generated from confirmed
data only. Every safety-critical section (redlines, bottomlines) is
assembled by plain code directly from the case/analysis — the only AI call
is for a handful of short prose pieces (case summary, opening plan,
question phrasing), and even that call only ever sees already-confirmed
content (see ai_client._format_brief_request).
"""

import hashlib
import json

from .ai_client import AIClient, BriefProseDraft, BriefRequest
from .models import BriefSectionState, LiveCard, NegotiationAnalysis, NegotiationBrief, NegotiationCase
from .package_service import validate_against_limits

_NFMV_CAP = 4
_ISSUE_CAP = 5
_OPTION_CAP = 8
_PACKAGE_CAP = 3
_QUESTION_CAP = 7
_LIVE_CARD_ITEM_CAP = 3


def _fingerprint(data) -> str:
    return hashlib.sha256(json.dumps(data, sort_keys=True, default=str).encode()).hexdigest()


def _section_source_data(section_id: str, case: NegotiationCase, analysis: NegotiationAnalysis):
    """The exact slice of case/analysis data each section is built from —
    used to fingerprint sections so an edit marks only the *affected*
    section(s) stale (SPEC §10.5: "Editing the case or the organization
    marks affected AI bases stale"), not the whole Brief indiscriminately.
    """
    def dump(m):
        return m.model_dump(mode="json")
    if section_id == "case_snapshot":
        return [dump(case.my_role) if case.my_role else None, dump(case.counterpart_role) if case.counterpart_role else None]
    if section_id == "objective_success_criteria":
        return [dump(case.objective) if case.objective else None, [dump(i) for i in case.issues]]
    if section_id == "walk_away_position":
        return dump(analysis.walk_away) if analysis.walk_away else None
    if section_id == "my_nfmv":
        return [dump(i) for i in analysis.interests if i.party == "me"]
    if section_id == "their_nfmv":
        return [dump(i) for i in analysis.interests if i.party == "counterpart"]
    if section_id == "positions_vs_interests":
        return [dump(link) for link in analysis.position_links]
    if section_id in ("islands_of_agreement", "contested_ground"):
        return [dump(a) for a in analysis.agreement_landscape]
    if section_id == "redlines":
        return [dump(r) for r in analysis.redlines]
    if section_id == "bottomlines":
        return [dump(b) for b in analysis.bottomlines]
    if section_id == "issue_map":
        return [dump(i) for i in case.issues]
    if section_id == "options":
        return [dump(o) for o in analysis.options]
    if section_id in ("packages", "haggle_plan"):
        return dump(analysis.haggle_plan) if analysis.haggle_plan else None
    if section_id == "uncertainties":
        return [
            [dump(r) for r in analysis.redlines],
            [dump(b) for b in analysis.bottomlines],
            [dump(c) for c in case.conflicts],
            case.organization.review_status if case.organization else None,
            [dump(q) for q in case.open_questions],
        ]
    if section_id == "key_events_deadlines":
        return [[dump(d) for d in case.deadlines], dump(case.organization) if case.organization else None]
    return None  # prose-only sections (questions_to_ask, opening_plan): freshness tied to regeneration, not a single field


def refresh_staleness(case: NegotiationCase, brief: NegotiationBrief) -> None:
    """Mark sections stale in place if their source data changed since they
    were generated. Never regenerates content and never touches notes,
    status, or pins — staleness is a warning until the user explicitly
    regenerates."""
    analysis = case.analysis or NegotiationAnalysis()
    for section in brief.sections:
        source_data = _section_source_data(section.section_id, case, analysis)
        if source_data is None:
            continue
        current_fingerprint = _fingerprint(source_data)
        if section.source_fingerprint is not None and current_fingerprint != section.source_fingerprint:
            section.stale = True


def _new_section(section_id: str, title: str, text: str) -> BriefSectionState:
    return BriefSectionState(section_id=section_id, title=title, ai_generated_base=text, status="tentative")


def _case_snapshot(case: NegotiationCase) -> BriefSectionState:
    my_role = case.my_role.current_value if case.my_role and case.my_role.current_value else "Unknown"
    counterpart_role = (
        case.counterpart_role.current_value if case.counterpart_role and case.counterpart_role.current_value else "Unknown"
    )
    return _new_section("case_snapshot", "Case Snapshot", f"My role: {my_role}\nCounterpart role: {counterpart_role}")


def _objective_success_criteria(prose: BriefProseDraft) -> BriefSectionState:
    criteria = "\n".join(f"- {c}" for c in prose.success_criteria) or "- None established"
    text = f"{prose.objective_summary}\n\nSuccess criteria:\n{criteria}"
    return _new_section("objective_success_criteria", "Objective & Success Criteria", text)


def _walk_away_position(analysis: NegotiationAnalysis, generation_notes: list[str]) -> BriefSectionState:
    wa = analysis.walk_away
    if wa is None:
        generation_notes.append("Preparation gap: walk-away analysis has not been run yet.")
        return _new_section("walk_away_position", "Walk-Away Position (private)", "Not established")

    if wa.batna_quality == "unknown":
        generation_notes.append("Preparation gap: BATNA quality is unknown.")

    lines = [
        f"BATNA: {wa.my_batna.current_value or 'Not established'} (quality: {wa.batna_quality})",
        "Reservation value: "
        + (wa.estimated_reservation_value.current_value if wa.estimated_reservation_value else "Not established"),
        "Triggers: " + ("; ".join(wa.walk_away_triggers) or "none set"),
        f"Exit script: {wa.exit_script}",
        "BATNA-improving actions: " + ("; ".join(wa.actions_to_improve_batna) or "none identified"),
    ]
    return _new_section("walk_away_position", "Walk-Away Position (private)", "\n".join(lines))


def _nfmv_section(analysis: NegotiationAnalysis, party: str, section_id: str, title: str) -> BriefSectionState:
    items = [i for i in analysis.interests if i.party == party][:_NFMV_CAP]
    lines = []
    for item in items:
        prefix = "Hypothesis — verify: " if item.is_hypothesis else ""
        status = f" [{item.statement.evidence_status}]" if item.statement.evidence_status != "explicit" else ""
        lines.append(f"[{item.category}] {prefix}{item.statement.current_value}{status}")
        if item.verification_question:
            lines.append(f"  Verify: {item.verification_question}")
    return _new_section(section_id, title, "\n".join(lines) or "None established")


def _positions_vs_interests(analysis: NegotiationAnalysis) -> BriefSectionState:
    interest_lookup = {i.id: i.statement.current_value for i in analysis.interests}
    lines = []
    for link in analysis.position_links:
        served = [interest_lookup.get(iid, iid) for iid in link.underlying_interest_ids]
        lines.append(f"({link.party}) \"{link.stated_position.current_value}\" -> {served} [{link.inference_basis}]")
        if link.reframe_question:
            lines.append(f"  Reframe: {link.reframe_question}")
        if link.misalignment_note:
            lines.append(f"  Misalignment: {link.misalignment_note}")
    return _new_section("positions_vs_interests", "Positions vs Interests", "\n".join(lines) or "None established")


def _islands_of_agreement(analysis: NegotiationAnalysis) -> BriefSectionState:
    lines = [f"[{a.kind}] {a.statement}" for a in analysis.agreement_landscape if a.standing == "shared"]
    return _new_section("islands_of_agreement", "Islands of Agreement", "\n".join(lines) or "None established")


def _contested_ground(analysis: NegotiationAnalysis) -> BriefSectionState:
    lines = []
    for a in analysis.agreement_landscape:
        if a.standing not in ("contested", "unverified"):
            continue
        line = f"[{a.kind}, {a.standing}] {a.statement}"
        if a.verification_question:
            line += f" — Verify: {a.verification_question}"
        if a.conflict_id:
            line += f" (conflict: {a.conflict_id})"
        lines.append(line)
    return _new_section("contested_ground", "Contested Ground", "\n".join(lines) or "None established")


def _redlines_section(analysis: NegotiationAnalysis, generation_notes: list[str]) -> BriefSectionState:
    """SPEC item 20: only confirmed_by_user=True redlines ever appear here."""
    confirmed = [r for r in analysis.redlines if r.confirmed_by_user]
    excluded = len(analysis.redlines) - len(confirmed)
    if excluded:
        generation_notes.append(f"{excluded} unconfirmed redline candidate(s) excluded from Redlines (see Uncertainties).")
    lines = [f"{r.statement.current_value} — {r.consequence_if_crossed}" for r in confirmed]
    return _new_section("redlines", "Redlines (Immovable)", "\n".join(lines) or "None confirmed")


def _bottomlines_section(analysis: NegotiationAnalysis, generation_notes: list[str]) -> BriefSectionState:
    """Unconfirmed bottomlines never appear as thresholds here — only in Uncertainties."""
    confirmed = [b for b in analysis.bottomlines if b.confirmed_by_user]
    excluded = len(analysis.bottomlines) - len(confirmed)
    if excluded:
        generation_notes.append(f"{excluded} unconfirmed bottomline candidate(s) excluded from Bottomlines (see Uncertainties).")
    lines = []
    for b in confirmed:
        provisional = " (provisional)" if b.provisional else ""
        lines.append(f"{b.threshold_value.current_value} ({b.direction}){provisional} — {b.rationale}")
    return _new_section("bottomlines", "Bottomlines (Flexible)", "\n".join(lines) or "None confirmed")


def _issue_map(case: NegotiationCase) -> BriefSectionState:
    lines = []
    for issue in case.issues[:_ISSUE_CAP]:
        target = issue.target.current_value if issue.target and issue.target.current_value else "unknown"
        lines.append(f"{issue.title}: target={target}, priority={issue.priority}, flexibility={issue.flexibility}, status={issue.status}")
    if len(case.issues) > _ISSUE_CAP:
        lines.append(f"...and {len(case.issues) - _ISSUE_CAP} more (collapsed)")
    return _new_section("issue_map", "Issue Map", "\n".join(lines) or "None established")


def _options_section(analysis: NegotiationAnalysis) -> BriefSectionState:
    lines = [
        f"[{o.option_type}] {o.title} — {o.description} (idea only, not an offer)"
        for o in analysis.options[:_OPTION_CAP]
    ]
    if len(analysis.options) > _OPTION_CAP:
        lines.append(f"...and {len(analysis.options) - _OPTION_CAP} more (collapsed by type)")
    return _new_section("options", "Expand the Pie — Options", "\n".join(lines) or "None generated")


def _packages_section(analysis: NegotiationAnalysis) -> BriefSectionState:
    plan = analysis.haggle_plan
    if plan is None:
        return _new_section("packages", "Packages (MESOs)", "None built yet")
    lines = []
    for package in plan.packages[:_PACKAGE_CAP]:
        warnings = validate_against_limits(package, analysis.redlines, analysis.bottomlines)
        line = f"{package.label}: give {package.what_i_give}, get {package.what_i_get} — {package.equivalence_note}"
        if warnings:
            line += " [WARNING: " + "; ".join(warnings) + "]"
        lines.append(line)
    return _new_section("packages", "Packages (MESOs)", "\n".join(lines) or "None built yet")


def _haggle_plan_section(analysis: NegotiationAnalysis) -> BriefSectionState:
    plan = analysis.haggle_plan
    if plan is None:
        return _new_section("haggle_plan", "Haggle Plan", "None built yet")
    lines = [f"Anchor: {plan.anchor} (justified by: {plan.justification_standard})"]
    for step in plan.concession_ladder:
        lines.append(f"  Step {step.order}: {step.from_value} -> {step.to_value}, ask: {step.ask_in_return}, trigger: {step.trigger_condition}")
    for tactic in plan.counter_tactics:
        lines.append(f"  Counter [{tactic.tactic}]: {tactic.response_line}")
    return _new_section("haggle_plan", "Haggle Plan", "\n".join(lines))


def _questions_section(prose: BriefProseDraft) -> BriefSectionState:
    questions = prose.questions_to_ask[:_QUESTION_CAP]
    return _new_section("questions_to_ask", "Questions to Ask", "\n".join(f"- {q}" for q in questions) or "None identified")


def _opening_plan_section(prose: BriefProseDraft) -> BriefSectionState:
    return _new_section("opening_plan", "Opening Plan", prose.opening_plan or "Not established")


def _uncertainties_section(case: NegotiationCase, analysis: NegotiationAnalysis, generation_notes: list[str]) -> BriefSectionState:
    """Never hidden for layout reasons (SPEC §10.2 row 17) — this is where
    every unconfirmed redline/bottomline candidate, numeric conflict,
    ordering ambiguity, and open question surfaces."""
    lines = []
    for r in analysis.redlines:
        if not r.confirmed_by_user:
            lines.append(f"Unconfirmed redline candidate: {r.statement.current_value}")
    for b in analysis.bottomlines:
        if not b.confirmed_by_user:
            lines.append(f"Unconfirmed bottomline candidate: {b.threshold_value.current_value}")
    for c in case.conflicts:
        lines.append(f"Numeric conflict: {c.field_description} ({[v.value for v in c.values]})")
    if case.organization and case.organization.review_status == "unreviewed":
        lines.append("Material ordering/grouping has not yet been reviewed by the user.")
    for q in case.open_questions:
        lines.append(f"Open question: {q.question}")
    lines.extend(generation_notes)
    return _new_section("uncertainties", "Uncertainties, Conflicts & Gaps", "\n".join(lines) or "None identified")


def _key_events_section(case: NegotiationCase) -> BriefSectionState:
    deadlines = [f"Deadline: {d.description} ({d.date_text or 'unknown date'})" for d in case.deadlines]
    if case.organization and case.organization.temporal_order_applicable:
        order = case.organization.confirmed_order or case.organization.proposed_order or []
        lines = [f"{i + 1}. {doc_id}" for i, doc_id in enumerate(order)] + deadlines
        return _new_section("key_events_deadlines", "Key Events / Deadlines", "\n".join(lines) or "None established")
    return _new_section("key_events_deadlines", "Key Events / Deadlines (thematic list)", "\n".join(deadlines) or "None established")


def generate_brief(case: NegotiationCase, *, ai_client: AIClient) -> NegotiationBrief:
    analysis = case.analysis or NegotiationAnalysis()
    prose = ai_client.generate_brief(BriefRequest(case=case))

    generation_notes: list[str] = []
    sections = [
        _case_snapshot(case),
        _objective_success_criteria(prose),
        _walk_away_position(analysis, generation_notes),
        _nfmv_section(analysis, "me", "my_nfmv", "My Needs / Fears / Motives / Values"),
        _nfmv_section(analysis, "counterpart", "their_nfmv", "Their Needs / Fears / Motives / Values"),
        _positions_vs_interests(analysis),
        _islands_of_agreement(analysis),
        _contested_ground(analysis),
        _redlines_section(analysis, generation_notes),
        _bottomlines_section(analysis, generation_notes),
        _issue_map(case),
        _options_section(analysis),
        _packages_section(analysis),
        _haggle_plan_section(analysis),
        _questions_section(prose),
        _opening_plan_section(prose),
        _uncertainties_section(case, analysis, generation_notes),
        _key_events_section(case),
    ]
    for section in sections:
        source_data = _section_source_data(section.section_id, case, analysis)
        if source_data is not None:
            section.source_fingerprint = _fingerprint(source_data)
    return NegotiationBrief(sections=sections, generation_notes=generation_notes)


def build_live_card(case: NegotiationCase, brief: NegotiationBrief | None = None) -> LiveCard:
    """Compressed view (SPEC §10.1) — same data source as the Prep Brief,
    hard-capped to `_LIVE_CARD_ITEM_CAP` items per list so it fits one
    screen. `brief` is optional only so a Live Card can be built without a
    full Brief regeneration; passing it in adds pinned sections and lets
    questions reuse the Brief's already-curated phrasing."""
    analysis = case.analysis or NegotiationAnalysis()
    wa = analysis.walk_away

    walk_away_line = "Not established"
    if wa is not None:
        reservation = wa.estimated_reservation_value.current_value if wa.estimated_reservation_value else "unknown"
        walk_away_line = f"BATNA: {wa.my_batna.current_value or 'unknown'}  ·  Reservation: {reservation}"

    redlines = [r.statement.current_value for r in analysis.redlines if r.confirmed_by_user and r.statement.current_value]
    my_interests = [
        i.statement.current_value for i in analysis.interests if i.party == "me" and i.statement.current_value
    ][:_LIVE_CARD_ITEM_CAP]
    their_interests = [
        i.statement.current_value for i in analysis.interests if i.party == "counterpart" and i.statement.current_value
    ][:_LIVE_CARD_ITEM_CAP]
    shared_facts = [a.statement for a in analysis.agreement_landscape if a.standing == "shared"][:_LIVE_CARD_ITEM_CAP]

    packages: list[str] = []
    if analysis.haggle_plan is not None:
        packages = [p.label for p in analysis.haggle_plan.packages[:_LIVE_CARD_ITEM_CAP]]

    questions: list[str] = []
    pinned: list[BriefSectionState] = []
    if brief is not None:
        questions_section = next((s for s in brief.sections if s.section_id == "questions_to_ask"), None)
        if questions_section is not None:
            questions = [
                line[2:] for line in questions_section.ai_generated_base.splitlines() if line.startswith("- ")
            ][:_LIVE_CARD_ITEM_CAP]
        pinned = [s for s in brief.sections if s.pinned]

    return LiveCard(
        walk_away_line=walk_away_line,
        redlines=redlines,
        my_top_interests=my_interests,
        their_top_interests=their_interests,
        shared_facts_opener=shared_facts,
        packages=packages,
        next_questions=questions,
        pinned_sections=pinned,
    )


def render_brief_markdown(
    brief: NegotiationBrief,
    *,
    include_judgment: bool = True,
    include_live_notes: bool = False,
) -> str:
    """SPEC §10.4: exports include My Judgment by default, live notes only
    if asked for. Contains no API key (never part of any model here) and
    no unnecessary full text — sections carry short excerpts, not raw
    documents."""
    lines = ["# Negotiation Brief", ""]
    if brief.generation_notes:
        lines.append("## Generation Notes")
        lines.extend(f"- {note}" for note in brief.generation_notes)
        lines.append("")

    for section in brief.sections:
        stale_flag = " (STALE — regenerate before relying on this)" if section.stale else ""
        pin_flag = " 📌" if section.pinned else ""
        lines.append(f"## {section.title}{stale_flag}{pin_flag}")
        lines.append(f"_Status: {section.status}_")
        lines.append("")
        lines.append(section.ai_generated_base)
        lines.append("")

        if include_judgment:
            judgments = [n for n in section.notes if n.note_type == "my_judgment"]
            if judgments:
                lines.append("**My Judgment:**")
                lines.extend(f"- {n.text} _({n.updated_at.isoformat()})_" for n in judgments)
                lines.append("")

        if include_live_notes:
            live_notes = [n for n in section.notes if n.note_type == "live_note"]
            if live_notes:
                lines.append("**Live Notes:**")
                lines.extend(f"- {n.text} _({n.updated_at.isoformat()})_" for n in live_notes)
                lines.append("")

    return "\n".join(lines)


def export_case_json(case: NegotiationCase) -> str:
    return case.model_dump_json(indent=2)


def export_pipeline_trace(case: NegotiationCase) -> str:
    """Optional export: per-stage intermediates only — no keys, no raw
    document text beyond the short excerpts already carried as evidence."""
    trace = {
        "documents": [d.model_dump(mode="json") for d in case.documents],
        "relationship_cues": [c.model_dump(mode="json") for c in case.relationship_cues],
        "organization": case.organization.model_dump(mode="json") if case.organization else None,
        "document_extractions": [e.model_dump(mode="json") for e in case.document_extractions],
        "conflicts": [c.model_dump(mode="json") for c in case.conflicts],
        "warnings": case.warnings,
    }
    return json.dumps(trace, indent=2, default=str)
