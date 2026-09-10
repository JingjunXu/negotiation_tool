"""Application configuration loaded from environment variables (SPEC §13.4).

`AI_PROVIDER`/`CLAUDE_CLI_*` below are NOT part of the SPEC §13.4 fixed
stack — they exist only for the `claude_cli` fallback backend (see
`claude_cli_client.py` and docs/DECISIONS.md). Leaving `AI_PROVIDER` unset
keeps the original OpenAI-or-fake behavior exactly as before.
"""

import logging
import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

logger = logging.getLogger(__name__)

load_dotenv()

REQUIRED_ENV_NAME = "negotiation_tool"


def check_environment() -> None:
    """Log the interpreter path and warn if not running inside the negotiation_tool env.

    Diagnostic only — never blocks startup, so a wrong-environment run surfaces
    immediately instead of resurfacing later as a missing-module error.
    """
    logger.info("Python interpreter: %s", sys.executable)
    if REQUIRED_ENV_NAME not in sys.prefix:
        logger.warning(
            "Not running inside the '%s' conda environment (sys.prefix=%s). "
            "Run `conda activate %s` before using this project.",
            REQUIRED_ENV_NAME,
            sys.prefix,
            REQUIRED_ENV_NAME,
        )


def _get_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _get_int(name: str, default: int, *, minimum: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        value = default
    else:
        try:
            value = int(raw)
        except ValueError as exc:
            raise ValueError(f"{name} must be an integer, got {raw!r}") from exc
    if value < minimum:
        raise ValueError(f"{name} must be >= {minimum}, got {value}")
    return value


def _default_claude_cli_path() -> str | None:
    found = shutil.which("claude")
    if found:
        return found
    fallback = Path.home() / ".local" / "bin" / "claude"
    return str(fallback) if fallback.exists() else None


@dataclass(frozen=True)
class Config:
    openai_api_key: str | None
    openai_model: str | None
    openai_store_responses: bool
    run_live_openai_tests: bool
    app_data_dir: Path
    max_upload_mb: int
    max_pdf_pages: int
    log_level: str
    ai_provider: str = "auto"  # "auto" | "openai" | "claude_cli" | "fake" — not in SPEC §13.4
    claude_cli_path: str | None = None
    claude_cli_model: str | None = None
    claude_cli_timeout_s: int = 300
    ingestion_max_concurrency: int = 5  # not in SPEC §13.4 — see docs/DECISIONS.md

    @property
    def effective_provider(self) -> str:
        """Resolve which AIClient backend to use.

        `ai_provider="auto"` (the default whenever AI_PROVIDER is unset)
        reproduces the original SPEC behavior exactly: OpenAI if a key is
        configured, fake mode otherwise. `claude_cli` is only ever selected
        by explicit opt-in (see docs/DECISIONS.md) — nothing changes for a
        project that never sets AI_PROVIDER.
        """
        if self.ai_provider == "claude_cli":
            return "claude_cli"
        if self.ai_provider == "fake":
            return "fake"
        return "openai" if self.openai_api_key else "fake"

    @property
    def is_fake_mode(self) -> bool:
        return self.effective_provider == "fake"

    def response_kwargs(self) -> dict:
        """Shared kwargs every OpenAI Responses API call must include."""
        return {"store": self.openai_store_responses}


def load_config() -> Config:
    return Config(
        openai_api_key=os.environ.get("OPENAI_API_KEY") or None,
        openai_model=os.environ.get("OPENAI_MODEL") or None,
        openai_store_responses=_get_bool("OPENAI_STORE_RESPONSES", False),
        run_live_openai_tests=_get_bool("RUN_LIVE_OPENAI_TESTS", False),
        app_data_dir=Path(os.environ.get("APP_DATA_DIR", "./data")),
        max_upload_mb=_get_int("MAX_UPLOAD_MB", 25, minimum=1),
        max_pdf_pages=_get_int("MAX_PDF_PAGES", 50, minimum=1),
        log_level=os.environ.get("LOG_LEVEL", "INFO"),
        ai_provider=os.environ.get("AI_PROVIDER", "auto").strip().lower() or "auto",
        claude_cli_path=os.environ.get("CLAUDE_CLI_PATH") or _default_claude_cli_path(),
        claude_cli_model=os.environ.get("CLAUDE_CLI_MODEL") or None,
        claude_cli_timeout_s=_get_int("CLAUDE_CLI_TIMEOUT_S", 300, minimum=1),
        ingestion_max_concurrency=_get_int("INGESTION_MAX_CONCURRENCY", 5, minimum=1),
    )


check_environment()
config = load_config()
