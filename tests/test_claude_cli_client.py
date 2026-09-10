"""ClaudeCliClient: the opt-in `claude` CLI backend (see docs/DECISIONS.md
and negotiation_copilot/claude_cli_client.py). Mirrors test_ai_client.py's
OpenAIClient tests method-for-method, but monkeypatches `client._invoke`
(the one subprocess-calling boundary) instead of an SDK call, so these
never touch a real subprocess or network (CLAUDE.md: tests never depend on
network). `_invoke` itself is tested separately against a mocked
`subprocess.run`.
"""

import json
import subprocess
from pathlib import Path

import pytest

from negotiation_copilot.ai_client import (
    AgreementRequest,
    AIAgreementBatch,
    AIInterestBatch,
    AIOptionDraft,
    AIPageReading,
    AIPositionLinkBatch,
    AIReviewedText,
    AIWalkAwayDraft,
    BilingualReplyRequest,
    BriefRequest,
    ConsolidationRequest,
    ConstraintRequest,
    DocumentMeta,
    ExtractionRequest,
    HaggleRequest,
    InterestRequest,
    MaterialOrganizationRequest,
    OptionRequest,
    PhraseInEnglishRequest,
    PositionMapRequest,
    PositionToMap,
    ReadPDFRequest,
    RelationshipCueRequest,
    WalkAwayRequest,
)
from negotiation_copilot.claude_cli_client import ClaudeCliClient, ClaudeCliError
from negotiation_copilot.config import Config
from negotiation_copilot.models import InterestItem, LanguageDraftRequest, NegotiationCase, ReviewedText, TextUnit


def _config(**overrides):
    defaults = dict(
        openai_api_key=None,
        openai_model=None,
        openai_store_responses=False,
        run_live_openai_tests=False,
        app_data_dir=Path("./data"),
        max_upload_mb=25,
        max_pdf_pages=50,
        log_level="INFO",
        ai_provider="claude_cli",
        claude_cli_path="/usr/bin/fake-claude",
        claude_cli_model="claude-sonnet-5",
        claude_cli_timeout_s=60,
    )
    defaults.update(overrides)
    return Config(**defaults)


def test_requires_claude_cli_path():
    with pytest.raises(ValueError):
        ClaudeCliClient(_config(claude_cli_path=None))


def test_cache_tag_includes_model():
    client = ClaudeCliClient(_config(claude_cli_model="claude-sonnet-5"))
    assert client.cache_tag == "claude_cli:claude-sonnet-5"


def test_cache_tag_falls_back_when_no_model_configured():
    client = ClaudeCliClient(_config(claude_cli_model=None))
    assert client.cache_tag == "claude_cli:default"


# --- _invoke: the subprocess boundary, mocked against subprocess.run ---


class _FakeCompletedProcess:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def test_invoke_builds_command_and_returns_structured_output(monkeypatch):
    client = ClaudeCliClient(_config())
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return _FakeCompletedProcess(stdout=json.dumps({"is_error": False, "structured_output": {"ok": True}}))

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = client._invoke(instructions="do X", user_content="some content", schema={"type": "object"})

    assert result == {"ok": True}
    cmd = captured["cmd"]
    assert cmd[0] == "/usr/bin/fake-claude"
    assert "--print" in cmd
    assert "--system-prompt" in cmd and cmd[cmd.index("--system-prompt") + 1] == "do X"
    assert "--model" in cmd and cmd[cmd.index("--model") + 1] == "claude-sonnet-5"
    assert cmd[-1] == "some content"  # prompt is the final positional arg
    tools_idx = cmd.index("--tools")
    assert cmd[tools_idx + 1] == ""  # all built-in tools disabled


def test_invoke_omits_model_flag_when_not_configured(monkeypatch):
    client = ClaudeCliClient(_config(claude_cli_model=None))

    def fake_run(cmd, **kwargs):
        return _FakeCompletedProcess(stdout=json.dumps({"is_error": False, "structured_output": {}}))

    monkeypatch.setattr(subprocess, "run", fake_run)
    client._invoke(instructions="x", user_content="y", schema={})
    # No exception means the model flag's absence didn't break anything;
    # explicit check that a fresh run without --model works at all:
    calls = []

    def recording_run(cmd, **kwargs):
        calls.append(cmd)
        return _FakeCompletedProcess(stdout=json.dumps({"is_error": False, "structured_output": {}}))

    monkeypatch.setattr(subprocess, "run", recording_run)
    client._invoke(instructions="x", user_content="y", schema={})
    assert "--model" not in calls[0]


def test_invoke_raises_on_nonzero_exit(monkeypatch):
    client = ClaudeCliClient(_config())
    monkeypatch.setattr(subprocess, "run", lambda cmd, **kwargs: _FakeCompletedProcess(returncode=1, stderr="boom"))
    with pytest.raises(ClaudeCliError):
        client._invoke(instructions="x", user_content="y", schema={})


def test_invoke_raises_on_non_json_stdout(monkeypatch):
    client = ClaudeCliClient(_config())
    monkeypatch.setattr(subprocess, "run", lambda cmd, **kwargs: _FakeCompletedProcess(stdout="not json"))
    with pytest.raises(ClaudeCliError):
        client._invoke(instructions="x", user_content="y", schema={})


def test_invoke_raises_when_is_error_flag_set(monkeypatch):
    client = ClaudeCliClient(_config())
    monkeypatch.setattr(
        subprocess, "run",
        lambda cmd, **kwargs: _FakeCompletedProcess(stdout=json.dumps({"is_error": True, "result": "refused"})),
    )
    with pytest.raises(ClaudeCliError):
        client._invoke(instructions="x", user_content="y", schema={})


def test_invoke_raises_when_structured_output_missing(monkeypatch):
    client = ClaudeCliClient(_config())
    monkeypatch.setattr(
        subprocess, "run", lambda cmd, **kwargs: _FakeCompletedProcess(stdout=json.dumps({"is_error": False}))
    )
    with pytest.raises(ClaudeCliError):
        client._invoke(instructions="x", user_content="y", schema={})


def test_invoke_raises_on_timeout(monkeypatch):
    client = ClaudeCliClient(_config())

    def fake_run(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd, kwargs.get("timeout"))

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(ClaudeCliError):
        client._invoke(instructions="x", user_content="y", schema={})


def test_invoke_raises_when_binary_missing(monkeypatch):
    client = ClaudeCliClient(_config())

    def fake_run(cmd, **kwargs):
        raise FileNotFoundError("no such file")

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(ClaudeCliError):
        client._invoke(instructions="x", user_content="y", schema={})


# --- Protocol methods: monkeypatch client._invoke, mirror test_ai_client.py ---


def test_read_pdf_never_invokes_and_returns_needs_review(monkeypatch):
    client = ClaudeCliClient(_config())
    monkeypatch.setattr(client, "_invoke", lambda **kwargs: pytest.fail("read_pdf must not call the CLI"))

    results = client.read_pdf(ReadPDFRequest(document_id="doc-1", filename="brief.pdf", data=b"%PDF-1.4", page_numbers=[1, 2]))

    assert [r.page_number for r in results] == [1, 2]
    assert all(r.status == "needs_review" for r in results)
    assert all(r.reading_method == "ai_pdf" for r in results)
    assert all("claude_cli_no_pdf_reading" in r.quality_flags for r in results)


def test_extract_relationship_cues_normalizes_to_relationship_cue(monkeypatch):
    client = ClaudeCliClient(_config())
    monkeypatch.setattr(
        client, "_invoke",
        lambda **kwargs: {
            "cues": [
                {
                    "cue_type": "date", "normalized_value": "March 3, 2025",
                    "excerpt": "dated March 3, 2025", "page_number": None, "paragraph_id": "para-1",
                }
            ]
        },
    )

    request = RelationshipCueRequest(
        document_id="doc-1", filename="brief.txt",
        units=[TextUnit(document_id="doc-1", paragraph_id="para-1", text="Agreement dated March 3, 2025.")],
    )
    cues = client.extract_relationship_cues(request)

    assert len(cues) == 1
    assert cues[0].document_id == "doc-1"
    assert cues[0].cue_type == "date"


def test_organize_materials_forces_unconfirmed_state(monkeypatch):
    client = ClaudeCliClient(_config())
    monkeypatch.setattr(
        client, "_invoke",
        lambda **kwargs: {
            "organization_mode": "chronological", "temporal_order_applicable": True,
            "proposed_order": ["doc-1", "doc-2"], "groups": [], "relations": [],
            "confidence": "high", "rationale": "Dated cues place doc-1 before doc-2.",
            "unresolved_ambiguities": [],
        },
    )

    request = MaterialOrganizationRequest(
        documents=[
            DocumentMeta(document_id="doc-1", filename="a.txt", upload_index=0),
            DocumentMeta(document_id="doc-2", filename="b.txt", upload_index=1),
        ],
        cues=[],
    )
    result = client.organize_materials(request)

    assert result.organization_mode == "chronological"
    assert result.confirmed_order is None
    assert result.review_status == "unreviewed"


def test_extract_document_normalizes_draft_and_generates_ids(monkeypatch):
    client = ClaudeCliClient(_config())
    monkeypatch.setattr(
        client, "_invoke",
        lambda **kwargs: {
            "summary": {"bullets": [], "role_and_purpose": "Role brief", "relationship_to_others": None, "warnings": []},
            "my_role": {"value": "Vendor", "evidence_status": "explicit", "evidence": []},
            "counterpart_role": None, "context": None, "objective": None,
            "interests": [], "positions": [], "batna": None,
            "issues": [
                {
                    "title": "Payment terms",
                    "my_position": {"value": "$120k in 30 days", "evidence_status": "explicit", "evidence": []},
                    "counterpart_position": None, "target": None, "acceptable_range": None,
                    "priority": "high", "flexibility": "flexible", "evidence": [],
                }
            ],
            "targets": [], "hard_constraints": [], "authority_limits": [], "deadlines": [],
            "possible_concessions": [], "counterpart_information": [], "open_questions": [], "warnings": [],
        },
    )

    request = ExtractionRequest(
        document_id="doc-1", filename="brief.txt",
        units=[TextUnit(document_id="doc-1", paragraph_id="para-1", text="We want $120k in 30 days.")],
    )
    extraction = client.extract_document(request)

    assert extraction.document_id == "doc-1"
    assert extraction.my_role.current_value == "Vendor"
    assert len(extraction.issues) == 1
    assert extraction.issues[0].id


def test_consolidate_case_returns_plan_not_full_case(monkeypatch):
    client = ClaudeCliClient(_config())
    monkeypatch.setattr(
        client, "_invoke",
        lambda **kwargs: {"issue_groups": [{"issue_refs": ["doc-1:a", "doc-2:b"], "merged_title": "Price"}]},
    )

    request = ConsolidationRequest(documents=[DocumentMeta(document_id="doc-1", filename="a.txt", upload_index=0)], extractions=[])
    result = client.consolidate_case(request)
    assert result.issue_groups[0].merged_title == "Price"


def test_analyze_interests_makes_separate_calls_per_party(monkeypatch):
    client = ClaudeCliClient(_config())
    calls = []

    def fake_invoke(*, instructions, user_content, schema):
        calls.append(user_content)
        party = "me" if "Party: me" in user_content else "counterpart"
        return {"items": [{"category": "need", "statement": {"value": f"{party} needs X", "evidence_status": "explicit", "evidence": []}, "verification_question": None}]}

    monkeypatch.setattr(client, "_invoke", fake_invoke)

    request = InterestRequest(my_context="My confidential stuff", counterpart_context="Shared stuff only")
    items = client.analyze_interests(request)

    assert len(calls) == 2
    assert len(items) == 2
    me_item = next(i for i in items if i.party == "me")
    counterpart_item = next(i for i in items if i.party == "counterpart")
    assert me_item.is_hypothesis is False
    assert counterpart_item.is_hypothesis is True


def test_map_positions_to_interests_skips_call_when_no_positions():
    client = ClaudeCliClient(_config())
    result = client.map_positions_to_interests(PositionMapRequest(positions=[], interests=[]))
    assert result == []


def test_map_positions_to_interests_returns_drafts(monkeypatch):
    client = ClaudeCliClient(_config())
    monkeypatch.setattr(
        client, "_invoke",
        lambda **kwargs: {
            "links": [
                {"ref": "issue:1:me", "underlying_interest_ids": ["interest-1"], "inference_basis": "explicit", "reframe_question": "Why?", "misalignment_note": None}
            ]
        },
    )
    request = PositionMapRequest(
        positions=[PositionToMap(ref="issue:1:me", party="me", statement=ReviewedText(current_value="$120k"))],
        interests=[InterestItem(id="interest-1", party="me", category="need", statement=ReviewedText(current_value="cash flow"))],
    )
    drafts = client.map_positions_to_interests(request)
    assert drafts[0].underlying_interest_ids == ["interest-1"]


def test_map_agreement_landscape_returns_drafts(monkeypatch):
    client = ClaudeCliClient(_config())
    monkeypatch.setattr(
        client, "_invoke",
        lambda **kwargs: {
            "items": [
                {
                    "kind": "fact", "statement": "Started in March", "standing": "shared",
                    "my_view": "March", "counterpart_view": "March", "conflict_id": None,
                    "verification_question": None, "evidence": [],
                }
            ]
        },
    )
    result = client.map_agreement_landscape(AgreementRequest(context="some context", conflicts=[]))
    assert result[0].standing == "shared"


def test_analyze_walk_away_returns_draft(monkeypatch):
    client = ClaudeCliClient(_config())
    monkeypatch.setattr(
        client, "_invoke",
        lambda **kwargs: {
            "my_batna": {"value": "Secondary buyer", "evidence_status": "inferred", "evidence": []},
            "batna_quality": "moderate", "quality_rationale": "x", "actions_to_improve_batna": [],
            "estimated_reservation_value": None, "reservation_derivation": None,
            "counterpart_batna_hypothesis": None, "tests_to_probe_their_batna": [],
            "walk_away_triggers": [], "exit_script": "We need more time.", "do_not_disclose": [],
        },
    )
    result = client.analyze_walk_away(WalkAwayRequest(context="some context"))
    assert result.batna_quality == "moderate"
    assert result.exit_script == "We need more time."


def test_classify_constraints_returns_draft(monkeypatch):
    client = ClaudeCliClient(_config())
    monkeypatch.setattr(
        client, "_invoke",
        lambda **kwargs: {
            "redline_candidates": [
                {
                    "statement": {"value": "No terms beyond 60 days", "evidence_status": "explicit", "evidence": []},
                    "source_type": "principal_mandate", "consequence_if_crossed": "Void", "evidence": [],
                }
            ],
            "bottomline_candidates": [
                {
                    "issue_id": None, "threshold_value": {"value": "$100k", "evidence_status": "inferred", "evidence": []},
                    "direction": "min", "rationale": "x", "linked_batna_reference": None, "risk_if_crossed": "y",
                    "revisit_conditions": [], "evidence": [],
                }
            ],
        },
    )
    result = client.classify_constraints(ConstraintRequest(context="some context", has_batna=False))
    assert len(result.redline_candidates) == 1
    assert len(result.bottomline_candidates) == 1


def test_generate_options_returns_drafts(monkeypatch):
    client = ClaudeCliClient(_config())
    monkeypatch.setattr(
        client, "_invoke",
        lambda **kwargs: {
            "options": [
                {
                    "title": "Staged payments", "description": "x", "option_type": "time",
                    "serves_my_interest_ids": ["interest-1"], "serves_their_interest_ids": [],
                    "cost_to_me": "low", "value_to_them_hypothesis": "medium", "depends_on": [], "evidence_status": "inferred",
                }
            ]
        },
    )
    result = client.generate_options(OptionRequest(context="ctx", interests=[]))
    assert result[0].option_type == "time"


def test_build_haggle_plan_returns_draft(monkeypatch):
    client = ClaudeCliClient(_config())
    monkeypatch.setattr(
        client, "_invoke",
        lambda **kwargs: {
            "packages": [], "anchor": "$130k", "justification_standard": "Market rate",
            "concession_ladder": [], "counter_tactics": [],
        },
    )
    result = client.build_haggle_plan(HaggleRequest(context="ctx", options=[], trade_currencies=[]))
    assert result.anchor == "$130k"


def test_generate_brief_returns_prose_draft(monkeypatch):
    client = ClaudeCliClient(_config())
    monkeypatch.setattr(
        client, "_invoke",
        lambda **kwargs: {
            "case_summary": "A vendor renewal negotiation.", "objective_summary": "Secure renewal.",
            "success_criteria": ["Achieve target price"], "opening_plan": "We're glad to continue this conversation.",
            "questions_to_ask": ["What is your timeline?"],
        },
    )
    result = client.generate_brief(BriefRequest(case=NegotiationCase()))
    assert result.case_summary == "A vendor renewal negotiation."


def _draft_request(**overrides):
    defaults = dict(mode="chinese_to_english", user_input="能不能120k成交？", input_language="zh", tone="neutral")
    defaults.update(overrides)
    return LanguageDraftRequest(**defaults)


def test_phrase_in_english_returns_variants(monkeypatch):
    client = ClaudeCliClient(_config())
    monkeypatch.setattr(
        client, "_invoke",
        lambda **kwargs: {
            "variants": [
                {"label": "natural", "english_draft": "Could we settle at $120k?", "chinese_back_translation": "能不能120k成交？", "risk_flags": []}
            ]
        },
    )
    result = client.phrase_in_english(PhraseInEnglishRequest(draft_request=_draft_request(), context=""))
    assert result[0].label == "natural"


def test_draft_bilingual_reply_returns_draft(monkeypatch):
    client = ClaudeCliClient(_config())
    monkeypatch.setattr(
        client, "_invoke",
        lambda **kwargs: {
            "counterpart_summary_zh": "他们同意了", "counterpart_summary_en": "They agreed",
            "points_to_verify": [], "chinese_draft": "好的", "english_draft": "Understood", "risk_flags": [],
        },
    )
    result = client.draft_bilingual_reply(BilingualReplyRequest(draft_request=_draft_request(mode="reply_to_counterpart"), context=""))
    assert result.english_draft == "Understood"
