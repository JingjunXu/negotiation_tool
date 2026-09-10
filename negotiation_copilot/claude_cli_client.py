"""Alternative AIClient backend: the local `claude` CLI in non-interactive
print mode, instead of a billed API key.

This is NOT part of the SPEC's fixed stack (CLAUDE.md: "OpenAI Python SDK
(Responses API)") — it exists only because a working OPENAI_API_KEY (and no
Anthropic Console key) was available in this build, and the user explicitly
asked for a Claude-backed alternative for local use. See docs/DECISIONS.md
for the full reasoning, including why `read_pdf` is deliberately NOT
implemented via this backend.

How it authenticates: `claude --print --output-format json --json-schema
<schema>` uses whatever login the `claude` binary itself already has
(Claude Code / Claude subscription) — there is no ANTHROPIC_API_KEY
involved. This makes the backend inherently local-machine-only: it only
works on a machine where `claude` is installed and logged in, and every
call spends that login's usage/quota, not a separate API bill.

Every text-generation method mirrors OpenAIClient's method of the same
name — same prompts/*.md instructions, same request/draft models, same
normalization helpers — so the two backends produce structurally identical
results and only differ in transport.
"""

import json
import subprocess

from pydantic import BaseModel

from .ai_client import (
    AgreementRequest,
    AIAgreementBatch,
    AIAgreementItemDraft,
    AIBilingualReplyDraft,
    AIEnglishPhraseBatch,
    AIEnglishVariantDraft,
    AIInterestBatch,
    AIOptionDraft,
    AIPageReading,
    AIPositionLinkBatch,
    AIPositionLinkDraft,
    AIWalkAwayDraft,
    BilingualReplyRequest,
    BriefProseDraft,
    BriefRequest,
    ConsolidationPlan,
    ConsolidationRequest,
    ConstraintClassificationDraft,
    ConstraintRequest,
    DocumentExtractionDraft,
    ExtractionRequest,
    HaggleRequest,
    HagglePlanDraft,
    InterestRequest,
    MaterialOrganizationDraft,
    MaterialOrganizationRequest,
    OptionBatch,
    OptionRequest,
    PhraseInEnglishRequest,
    PositionMapRequest,
    ReadPDFRequest,
    RelationshipCueBatch,
    RelationshipCueRequest,
    WalkAwayRequest,
    _format_brief_request,
    _format_consolidation_request,
    _format_haggle_request,
    _format_language_request,
    _format_option_request,
    _format_organization_request,
    _format_position_map_request,
    _format_unit,
    _load_prompt,
    _to_page_results,
    document_extraction_from_draft,
    organization_result_from_draft,
    relationship_cues_from_batch,
    reviewed_from_draft_keep_document_ids,
)
from .config import Config
from .models import DocumentExtraction, InterestItem, MaterialOrganizationResult, PDFPageResult, RelationshipCue


class ClaudeCliError(RuntimeError):
    pass


class ClaudeCliClient:
    """Real AIClient implementation backed by `claude --print`.

    `read_pdf` intentionally never invokes the CLI: doing so needs the Read
    tool, which needs broad file-access permissions granted to an
    unattended subprocess — the same pattern Claude Code's own safety
    checks flag as risky, and one this project shouldn't bake into a
    button-triggered pipeline. It honestly reports every requested page as
    `needs_review` instead of fabricating a reading, exactly like
    FakeAIClient's placeholder for the same situation (see
    docs/DECISIONS.md). In practice this rarely matters — native pypdf
    extraction already handles the vast majority of real documents.
    """

    def __init__(self, config: Config):
        if not config.claude_cli_path:
            raise ValueError(
                "No `claude` executable found (checked PATH and ~/.local/bin/claude). "
                "Set CLAUDE_CLI_PATH explicitly, or install the Claude Code CLI."
            )
        self._config = config

    @property
    def cache_tag(self) -> str:
        return f"claude_cli:{self._config.claude_cli_model or 'default'}"

    def _invoke(self, *, instructions: str, user_content: str, schema: dict) -> dict:
        """Run one `claude --print` call and return its `structured_output`.

        Split out as its own method (rather than inlined in `_parse`) so
        tests can monkeypatch just this transport boundary, the same way
        OpenAIClient tests monkeypatch `client._client.responses.parse`.
        """
        cmd = [
            self._config.claude_cli_path,
            "--print",
            "--output-format", "json",
            "--system-prompt", instructions,
            "--json-schema", json.dumps(schema),
            "--tools", "",
        ]
        if self._config.claude_cli_model:
            cmd += ["--model", self._config.claude_cli_model]
        cmd.append(user_content)

        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=self._config.claude_cli_timeout_s)
        except subprocess.TimeoutExpired as exc:
            raise ClaudeCliError(f"claude CLI timed out after {self._config.claude_cli_timeout_s}s") from exc
        except OSError as exc:
            raise ClaudeCliError(f"could not run claude CLI at {self._config.claude_cli_path!r}: {exc}") from exc

        if proc.returncode != 0:
            raise ClaudeCliError(f"claude CLI exited {proc.returncode}: {proc.stderr.strip()}")

        try:
            payload = json.loads(proc.stdout)
        except json.JSONDecodeError as exc:
            raise ClaudeCliError(f"claude CLI returned non-JSON output: {proc.stdout[:200]!r}") from exc

        if payload.get("is_error"):
            raise ClaudeCliError(f"claude CLI reported an error: {payload.get('result')!r}")

        structured = payload.get("structured_output")
        if structured is None:
            raise ClaudeCliError("claude CLI did not return structured_output")
        return structured

    def _parse(self, *, prompt_file: str, user_content: str, response_model: type[BaseModel]) -> BaseModel:
        structured = self._invoke(
            instructions=_load_prompt(prompt_file),
            user_content=user_content,
            schema=response_model.model_json_schema(),
        )
        return response_model.model_validate(structured)

    def read_pdf(self, request: ReadPDFRequest) -> list[PDFPageResult]:
        pages = [
            AIPageReading(
                page_number=page_number, content="", key_items=[],
                quality_flags=["claude_cli_no_pdf_reading"], status="needs_review",
            )
            for page_number in request.page_numbers
        ]
        return _to_page_results(request.document_id, "ai_pdf", pages)

    def extract_relationship_cues(self, request: RelationshipCueRequest) -> list[RelationshipCue]:
        units_text = "\n\n".join(_format_unit(unit) for unit in request.units)
        batch = self._parse(
            prompt_file="extract_relationship_cues.md",
            user_content=f"Document: {request.filename}\n\n{units_text}",
            response_model=RelationshipCueBatch,
        )
        return relationship_cues_from_batch(request.document_id, batch)

    def organize_materials(self, request: MaterialOrganizationRequest) -> MaterialOrganizationResult:
        draft = self._parse(
            prompt_file="organize_materials.md",
            user_content=_format_organization_request(request),
            response_model=MaterialOrganizationDraft,
        )
        return organization_result_from_draft(draft)

    def extract_document(self, request: ExtractionRequest) -> DocumentExtraction:
        units_text = "\n\n".join(_format_unit(unit) for unit in request.units)
        draft = self._parse(
            prompt_file="summarize_and_extract.md",
            user_content=f"Document: {request.filename}\n\n{units_text}",
            response_model=DocumentExtractionDraft,
        )
        return document_extraction_from_draft(request.document_id, draft)

    def consolidate_case(self, request: ConsolidationRequest) -> ConsolidationPlan:
        return self._parse(
            prompt_file="consolidate.md",
            user_content=_format_consolidation_request(request),
            response_model=ConsolidationPlan,
        )

    def analyze_interests(self, request: InterestRequest) -> list[InterestItem]:
        return self._analyze_interests_for_party("me", request.my_context) + self._analyze_interests_for_party(
            "counterpart", request.counterpart_context
        )

    def _analyze_interests_for_party(self, party: str, context: str) -> list[InterestItem]:
        if not context.strip():
            return []
        batch = self._parse(
            prompt_file="analyze_interests.md",
            user_content=f"Party: {party}\n\n{context}",
            response_model=AIInterestBatch,
        )
        return [
            InterestItem(
                party=party,
                category=item.category,
                statement=reviewed_from_draft_keep_document_ids(item.statement),
                verification_question=item.verification_question,
                is_hypothesis=(party == "counterpart"),
            )
            for item in batch.items
        ]

    def map_positions_to_interests(self, request: PositionMapRequest) -> list[AIPositionLinkDraft]:
        if not request.positions:
            return []
        batch = self._parse(
            prompt_file="map_positions_to_interests.md",
            user_content=_format_position_map_request(request),
            response_model=AIPositionLinkBatch,
        )
        return batch.links

    def map_agreement_landscape(self, request: AgreementRequest) -> list[AIAgreementItemDraft]:
        conflicts_text = "\n".join(f"- id={c.id}: {c.field_description}" for c in request.conflicts)
        batch = self._parse(
            prompt_file="map_agreement_landscape.md",
            user_content=f"{request.context}\n\nExisting conflicts:\n{conflicts_text}",
            response_model=AIAgreementBatch,
        )
        return batch.items

    def analyze_walk_away(self, request: WalkAwayRequest) -> AIWalkAwayDraft:
        return self._parse(prompt_file="analyze_walk_away.md", user_content=request.context, response_model=AIWalkAwayDraft)

    def classify_constraints(self, request: ConstraintRequest) -> ConstraintClassificationDraft:
        content = f"Usable BATNA/reservation value exists: {request.has_batna}\n\n{request.context}"
        return self._parse(
            prompt_file="classify_constraints.md", user_content=content, response_model=ConstraintClassificationDraft
        )

    def generate_options(self, request: OptionRequest) -> list[AIOptionDraft]:
        batch = self._parse(
            prompt_file="generate_options.md",
            user_content=_format_option_request(request),
            response_model=OptionBatch,
        )
        return batch.options

    def build_haggle_plan(self, request: HaggleRequest) -> HagglePlanDraft:
        return self._parse(
            prompt_file="build_haggle_plan.md",
            user_content=_format_haggle_request(request),
            response_model=HagglePlanDraft,
        )

    def generate_brief(self, request: BriefRequest) -> BriefProseDraft:
        return self._parse(
            prompt_file="generate_brief.md",
            user_content=_format_brief_request(request.case),
            response_model=BriefProseDraft,
        )

    def phrase_in_english(self, request: PhraseInEnglishRequest) -> list[AIEnglishVariantDraft]:
        batch = self._parse(
            prompt_file="phrase_in_english.md",
            user_content=_format_language_request(request.draft_request, request.context),
            response_model=AIEnglishPhraseBatch,
        )
        return batch.variants

    def draft_bilingual_reply(self, request: BilingualReplyRequest) -> AIBilingualReplyDraft:
        return self._parse(
            prompt_file="draft_bilingual_reply.md",
            user_content=_format_language_request(request.draft_request, request.context),
            response_model=AIBilingualReplyDraft,
        )
