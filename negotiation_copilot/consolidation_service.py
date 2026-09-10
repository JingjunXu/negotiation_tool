"""Cross-document consolidation (SPEC §7.3).

The AI (via `ConsolidationPlan`) only decides which issues across documents
are duplicates of each other. All merge arithmetic here — unioning evidence,
detecting divergent values, building `Conflict` records — is deterministic
so evidence is never silently rewritten, dropped, or overwritten (SPEC
§14.1 items 9-11). See docs/DECISIONS.md T3.5.
"""

from .ai_client import AIClient, ConsolidationRequest, DocumentMeta
from .models import (
    Conflict,
    ConflictingValue,
    DocumentExtraction,
    DocumentRecord,
    Evidence,
    MaterialOrganizationResult,
    NegotiationCase,
    NegotiationIssue,
    ReviewedText,
)

_STATUS_PRIORITY = {"unknown": 0, "inferred": 1, "explicit": 2, "user_confirmed": 3}


def _best_status(statuses: list[str]) -> str:
    return max(statuses, key=lambda s: _STATUS_PRIORITY.get(s, -1))


def _representative_document_id(rt: ReviewedText) -> str:
    return rt.evidence[0].document_id if rt.evidence else "unknown"


def _representative_evidence(rt: ReviewedText) -> Evidence:
    if rt.evidence:
        return rt.evidence[0]
    return Evidence(document_id="unknown", excerpt=rt.current_value or "")


def merge_reviewed_texts(values: list[ReviewedText], field_description: str) -> tuple[ReviewedText | None, Conflict | None]:
    """Merge same-valued ReviewedTexts (union their evidence); if values
    genuinely diverge, keep one as current and record a Conflict with every
    distinct value — never silently pick a winner (SPEC item 10)."""
    if not values:
        return None, None

    groups: dict[str, list[ReviewedText]] = {}
    for rt in values:
        key = (rt.current_value or "").strip().lower()
        groups.setdefault(key, []).append(rt)

    if len(groups) == 1:
        items = next(iter(groups.values()))
        if len(items) == 1:
            # Only one source for this value: pass it through unchanged so
            # ai_original_value and evidence stay byte-for-byte what T3.4
            # produced (SPEC item 11), rather than reconstructing an
            # equivalent-but-different object.
            return items[0], None
        merged_evidence = [e for rt in items for e in rt.evidence]
        status = _best_status([rt.evidence_status for rt in items])
        value = items[0].current_value
        return ReviewedText(current_value=value, ai_original_value=value, evidence_status=status, evidence=merged_evidence), None

    conflicting_values = [
        ConflictingValue(
            document_id=_representative_document_id(items[0]),
            value=items[0].current_value or "",
            evidence=_representative_evidence(items[0]),
        )
        for items in groups.values()
    ]
    conflict = Conflict(field_description=field_description, values=conflicting_values)
    return values[0], conflict


def _merge_issue_group(
    refs: list[str],
    merged_title: str,
    issue_by_ref: dict[str, NegotiationIssue],
) -> tuple[NegotiationIssue | None, list[Conflict]]:
    issues = [issue_by_ref[r] for r in refs if r in issue_by_ref]
    if not issues:
        return None, []

    conflicts: list[Conflict] = []
    target, target_conflict = merge_reviewed_texts(
        [i.target for i in issues if i.target is not None], f"Target for issue '{merged_title}' differs across documents"
    )
    if target_conflict:
        conflicts.append(target_conflict)
    acceptable_range, range_conflict = merge_reviewed_texts(
        [i.acceptable_range for i in issues if i.acceptable_range is not None],
        f"Acceptable range for issue '{merged_title}' differs across documents",
    )
    if range_conflict:
        conflicts.append(range_conflict)

    my_position = next((i.my_position for i in issues if i.my_position is not None), None)
    counterpart_position = next((i.counterpart_position for i in issues if i.counterpart_position is not None), None)
    priority = next((i.priority for i in issues if i.priority != "unknown"), "unknown")
    flexibility = next((i.flexibility for i in issues if i.flexibility != "unknown"), "unknown")
    merged_evidence = [e for i in issues for e in i.evidence]

    merged_issue = NegotiationIssue(
        title=merged_title,
        my_position=my_position,
        counterpart_position=counterpart_position,
        target=target,
        acceptable_range=acceptable_range,
        priority=priority,
        flexibility=flexibility,
        evidence=merged_evidence,
    )
    return merged_issue, conflicts


def _union(extractions: list[DocumentExtraction], field: str) -> list:
    return [item for extraction in extractions for item in getattr(extraction, field)]


def consolidate_case(
    documents: list[DocumentRecord],
    organization: MaterialOrganizationResult | None,
    extractions: list[DocumentExtraction],
    *,
    ai_client: AIClient,
) -> NegotiationCase:
    doc_metas = [DocumentMeta(document_id=d.document_id, filename=d.filename, upload_index=d.upload_index) for d in documents]
    plan = ai_client.consolidate_case(ConsolidationRequest(documents=doc_metas, extractions=extractions))

    issue_by_ref = {f"{e.document_id}:{issue.id}": issue for e in extractions for issue in e.issues}
    grouped_refs: set[str] = set()
    merged_issues: list[NegotiationIssue] = []
    conflicts: list[Conflict] = []

    for group in plan.issue_groups:
        valid_refs = [r for r in group.issue_refs if r in issue_by_ref]
        if not valid_refs:
            continue
        merged_issue, issue_conflicts = _merge_issue_group(valid_refs, group.merged_title, issue_by_ref)
        if merged_issue is not None:
            merged_issues.append(merged_issue)
            conflicts.extend(issue_conflicts)
            grouped_refs.update(valid_refs)

    for ref, issue in issue_by_ref.items():
        if ref not in grouped_refs:
            merged_issues.append(issue)

    def _singular_field(name: str) -> ReviewedText | None:
        values = [v for e in extractions if (v := getattr(e, name)) is not None]
        merged, conflict = merge_reviewed_texts(values, f"{name} differs across documents")
        if conflict:
            conflicts.append(conflict)
        return merged

    warnings = [w for e in extractions for w in e.warnings]

    return NegotiationCase(
        documents=documents,
        document_extractions=extractions,
        organization=organization,
        my_role=_singular_field("my_role"),
        counterpart_role=_singular_field("counterpart_role"),
        context=_singular_field("context"),
        objective=_singular_field("objective"),
        interests=_union(extractions, "interests"),
        positions=_union(extractions, "positions"),
        batna=_singular_field("batna"),
        issues=merged_issues,
        targets=_union(extractions, "targets"),
        hard_constraints=_union(extractions, "hard_constraints"),
        authority_limits=_union(extractions, "authority_limits"),
        deadlines=_union(extractions, "deadlines"),
        possible_concessions=_union(extractions, "possible_concessions"),
        counterpart_information=_union(extractions, "counterpart_information"),
        open_questions=_union(extractions, "open_questions"),
        conflicts=conflicts,
        warnings=warnings,
    )
