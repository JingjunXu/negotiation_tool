"""Session-wide test safety net.

CLAUDE.md: "Do not make tests depend on network or on a chat session."
A developer's local `.env` may configure a real AI provider for actually
*running* the app (an OpenAI key, or `AI_PROVIDER=claude_cli` — see
negotiation_copilot/claude_cli_client.py) — that must never leak into what
page tests do when they call `get_ai_client()` without an explicit
override. This forces fake mode for every test in this suite, regardless
of whatever provider the local `.env` configures for real use.
"""

import dataclasses

import pytest

from negotiation_copilot import config as config_module
from negotiation_copilot.pages import _common as pages_common


@pytest.fixture(autouse=True)
def _force_fake_ai_provider(monkeypatch):
    fake_config = dataclasses.replace(config_module.config, ai_provider="fake", openai_api_key=None)
    monkeypatch.setattr(pages_common, "config", fake_config)
