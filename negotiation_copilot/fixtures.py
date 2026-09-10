"""Hardcoded demo case used by the M1 UI shell (T1.4).

Every page prefers the real pipeline output in `st.session_state["case"]`
once later milestones populate it; this fixture only backs the shell before
that data exists, and must never be mistaken for real negotiation content.
"""

from .models import (
    AgreementItem,
    Bottomline,
    ConcessionStep,
    Conflict,
    ConflictingValue,
    Constraint,
    CounterTactic,
    Deadline,
    DocumentGroup,
    DocumentRecord,
    DocumentRelation,
    Evidence,
    HagglePlan,
    InterestItem,
    MaterialOrganizationResult,
    NegotiationAnalysis,
    NegotiationCase,
    NegotiationIssue,
    NegotiationOption,
    OpenQuestion,
    PositionInterestLink,
    Redline,
    RelationshipCue,
    ReviewedText,
    TradeCurrency,
    TradePackage,
    WalkAwayAnalysis,
)


def _evidence(doc_id: str = "doc-1") -> Evidence:
    return Evidence(document_id=doc_id, page_number=2, paragraph_id="p3", excerpt="an excerpt from the material")


def _reviewed(value: str, status: str = "explicit") -> ReviewedText:
    return ReviewedText(current_value=value, ai_original_value=value, evidence_status=status, evidence=[_evidence()])


def sample_case() -> NegotiationCase:
    interest_me = InterestItem(
        party="me", category="need", statement=_reviewed("Need cash flow within 30 days"), is_hypothesis=False
    )
    interest_them = InterestItem(
        party="counterpart",
        category="fear",
        statement=_reviewed("Fear of setting a bad precedent", status="inferred"),
        verification_question="Would a one-time exception concern you for future deals?",
        is_hypothesis=True,
    )

    position_link = PositionInterestLink(
        party="me",
        stated_position=_reviewed("We want $120k in 30 days"),
        underlying_interest_ids=[interest_me.id],
        inference_basis="explicit statement in role brief",
        reframe_question="What would faster payment let you do?",
    )

    agreement_item = AgreementItem(
        kind="fact",
        statement="Both sides agree the contract started in March",
        standing="shared",
        my_view="March 1",
        counterpart_view="March 1",
        evidence=[_evidence()],
    )

    walk_away = WalkAwayAnalysis(
        my_batna=_reviewed("Sell to a secondary buyer at a 10% discount"),
        batna_quality="moderate",
        quality_rationale="Secondary buyer confirmed interest but at a lower price",
        actions_to_improve_batna=["Get a written offer from the secondary buyer"],
        estimated_reservation_value=_reviewed("$100k", status="inferred"),
        reservation_derivation="10% below primary ask, matching secondary buyer discount",
        counterpart_batna_hypothesis=_reviewed("Unknown alternative supplier", status="unknown"),
        tests_to_probe_their_batna=["Ask how urgent their timeline really is"],
        walk_away_triggers=["They refuse any written commitment"],
        exit_script="We appreciate the discussion, but we can't move forward on these terms today.",
        do_not_disclose=["reservation_value"],
    )

    redline = Redline(
        statement=_reviewed("Cannot accept payment terms beyond 60 days"),
        source_type="principal_mandate",
        consequence_if_crossed="Deal is void per client mandate",
        confirmed_by_user=True,
        evidence=[_evidence()],
    )

    bottomline = Bottomline(
        issue_id=None,
        threshold_value=_reviewed("$100k", status="inferred"),
        direction="min",
        rationale="Below BATNA-equivalent value",
        linked_batna_reference="my_batna",
        risk_if_crossed="Deal becomes worse than walking away",
        revisit_conditions=["Secondary buyer offer improves"],
        provisional=False,
        confirmed_by_user=True,
        evidence=[_evidence()],
    )

    option = NegotiationOption(
        title="Staged payment schedule",
        description="Split payment into three milestones instead of one lump sum.",
        option_type="time",
        serves_my_interest_ids=[interest_me.id],
        serves_their_interest_ids=[interest_them.id],
        cost_to_me="low",
        value_to_them_hypothesis="medium",
        depends_on=["Counterpart can process partial payments"],
        evidence_status="inferred",
    )

    package = TradePackage(
        label="Balanced package",
        option_ids=[option.id],
        what_i_give=["Extended timeline"],
        what_i_get=["Full price"],
        equivalence_note="Roughly equal value to package B",
    )

    haggle_plan = HagglePlan(
        anchor="$130k, net 15",
        justification_standard="Market rate for comparable contracts",
        trade_currencies=[
            TradeCurrency(
                item="Timeline flexibility", cost_to_me="low", value_to_them_hypothesis="high", direction="i_can_give"
            )
        ],
        packages=[package],
        concession_ladder=[
            ConcessionStep(
                order=1,
                issue_id=None,
                from_value="$130k",
                to_value="$120k",
                ask_in_return="Net 15 payment",
                trigger_condition="They commit to written terms",
            )
        ],
        counter_tactics=[
            CounterTactic(
                tactic="extreme anchor",
                response_line="That's well outside market rate; let's ground this in comparable deals.",
            )
        ],
    )

    analysis = NegotiationAnalysis(
        interests=[interest_me, interest_them],
        position_links=[position_link],
        agreement_landscape=[agreement_item],
        walk_away=walk_away,
        redlines=[redline],
        bottomlines=[bottomline],
        options=[option],
        haggle_plan=haggle_plan,
        generation_notes=["Used confirmed BATNA; excluded unconfirmed target"],
    )

    document = DocumentRecord(
        filename="role_brief.pdf",
        upload_index=0,
        file_type="pdf",
        size_bytes=1024,
        sha256="a" * 64,
        page_count=5,
        parse_method="native_text",
        page_reading_methods={1: "native_text", 2: "ai_pdf"},
        pages_needing_review=[3],
        scope="my_confidential",
        processing_status="processed",
    )

    organization = MaterialOrganizationResult(
        organization_mode="thematic",
        temporal_order_applicable=False,
        proposed_order=None,
        confirmed_order=None,
        groups=[
            DocumentGroup(
                name="Financial docs",
                document_ids=[document.document_id],
                organizing_reason="Both cover payment terms",
            )
        ],
        relations=[
            DocumentRelation(
                source_document_id=document.document_id,
                target_document_id=None,
                relation_type="independent",
                explanation="No cross references found",
                evidence=[_evidence()],
                confidence="high",
            )
        ],
    )

    conflict = Conflict(
        field_description="Payment deadline",
        values=[ConflictingValue(document_id=document.document_id, value="30 days", evidence=_evidence())],
    )

    cues = [
        RelationshipCue(
            document_id=document.document_id,
            cue_type="document_role",
            normalized_value="role brief",
            excerpt="This role brief describes the negotiation context",
            page_number=1,
        ),
        RelationshipCue(
            document_id=document.document_id,
            cue_type="date",
            normalized_value=None,
            excerpt="no explicit date found in this document",
            page_number=1,
        ),
    ]

    return NegotiationCase(
        documents=[document],
        relationship_cues=cues,
        organization=organization,
        my_role=_reviewed("Vendor negotiating renewal"),
        counterpart_role=_reviewed("Client procurement lead"),
        context=_reviewed("Annual contract renewal"),
        objective=_reviewed("Secure renewal above reservation value"),
        interests=[_reviewed("Fast payment")],
        positions=[_reviewed("$120k in 30 days")],
        batna=_reviewed("Secondary buyer at 10% discount"),
        issues=[NegotiationIssue(title="Payment terms", priority="high", flexibility="flexible")],
        targets=[_reviewed("$130k")],
        hard_constraints=[
            Constraint(statement=_reviewed("Cannot exceed 60 day terms"), source_type="principal_mandate")
        ],
        authority_limits=[_reviewed("Cannot approve over $150k without director sign-off")],
        deadlines=[Deadline(description="Contract expires", date_text="end of month")],
        possible_concessions=[_reviewed("Extended timeline")],
        counterpart_information=[_reviewed("Procurement lead reports to CFO")],
        open_questions=[OpenQuestion(question="Is there flexibility on payment schedule?")],
        conflicts=[conflict],
        warnings=["Page 3 of role_brief.pdf needs manual review"],
        analysis=analysis,
    )
