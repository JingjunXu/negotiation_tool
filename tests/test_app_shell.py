"""T1.4 acceptance: every page renders with no OpenAI key configured."""

from streamlit.testing.v1 import AppTest

PAGE_MODULES = [
    "materials",
    "pipeline",
    "negotiation_map",
    "strategy_lab",
    "brief_builder",
    "live_workspace",
]


def _page_script(module_name: str) -> str:
    return (
        f"from negotiation_copilot.pages import {module_name}\n"
        f"{module_name}.render()\n"
    )


def test_all_pages_render_without_exception(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    for module_name in PAGE_MODULES:
        at = AppTest.from_string(_page_script(module_name))
        at.run(timeout=15)
        assert not at.exception, f"{module_name} raised: {at.exception}"


def test_app_script_starts_without_exception(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    at = AppTest.from_file("../app.py")
    at.run()
    assert not at.exception
