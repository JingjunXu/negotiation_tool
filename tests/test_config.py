import logging

from negotiation_copilot import config as config_module


def test_missing_key_is_fake_mode(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    cfg = config_module.load_config()
    assert cfg.openai_api_key is None
    assert cfg.is_fake_mode is True


def test_present_key_is_not_fake_mode(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    cfg = config_module.load_config()
    assert cfg.is_fake_mode is False


def test_store_responses_false_by_default(monkeypatch):
    monkeypatch.delenv("OPENAI_STORE_RESPONSES", raising=False)
    cfg = config_module.load_config()
    assert cfg.openai_store_responses is False
    assert cfg.response_kwargs() == {"store": False}


def test_store_responses_explicit_false(monkeypatch):
    monkeypatch.setenv("OPENAI_STORE_RESPONSES", "false")
    cfg = config_module.load_config()
    assert cfg.openai_store_responses is False
    assert cfg.response_kwargs()["store"] is False


def test_store_responses_true(monkeypatch):
    monkeypatch.setenv("OPENAI_STORE_RESPONSES", "true")
    cfg = config_module.load_config()
    assert cfg.openai_store_responses is True


def test_invalid_max_pdf_pages_raises(monkeypatch):
    monkeypatch.setenv("MAX_PDF_PAGES", "0")
    try:
        config_module.load_config()
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_guard_warns_outside_environment(monkeypatch, caplog):
    monkeypatch.setattr(config_module.sys, "prefix", "/usr/local/some/other/env")
    with caplog.at_level(logging.WARNING):
        config_module.check_environment()
    assert any("negotiation_tool" in record.message for record in caplog.records)


def test_guard_silent_inside_environment(monkeypatch, caplog):
    monkeypatch.setattr(config_module.sys, "prefix", "/opt/miniconda3/envs/negotiation_tool")
    with caplog.at_level(logging.WARNING):
        config_module.check_environment()
    assert not any(record.levelno >= logging.WARNING for record in caplog.records)
