"""Application configuration loaded from environment variables (SPEC §13.4)."""

import logging
import os
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

    @property
    def is_fake_mode(self) -> bool:
        return not self.openai_api_key

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
    )


check_environment()
config = load_config()
