from pathlib import Path

from bot.browser_worker import resolve_browser_executable


def test_resolve_browser_executable_ignores_missing_configured_path(monkeypatch, tmp_path: Path):
    browser = tmp_path / "chromium"
    browser.write_text("#!/bin/sh\n")
    browser.chmod(0o755)
    monkeypatch.setattr(
        "bot.browser_worker.shutil.which",
        lambda name: str(browser) if name == "chromium" else None,
    )

    assert resolve_browser_executable(str(tmp_path / "missing-chromium")) == str(browser)


def test_resolve_browser_executable_returns_empty_when_no_browser_exists(monkeypatch):
    monkeypatch.setattr("bot.browser_worker.shutil.which", lambda _name: None)

    assert resolve_browser_executable("/definitely/missing/chromium") == ""
