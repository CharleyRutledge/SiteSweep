"""When Playwright can't download its own Chromium (e.g. Claude Code on the web, whose network blocks the download
server), the run uses the Chromium that came with the computer instead of stopping."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright

from harness import base_config, invoke_cli
from ui_automation import browsers


def _failed_download(*args, **kwargs) -> subprocess.CompletedProcess:  # noqa: ANN002, ANN003
    return subprocess.CompletedProcess(args, 1)


@pytest.fixture
def offline(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    """Chromium and Firefox missing, and the download fails."""
    monkeypatch.setattr(browsers, "missing_browsers", lambda names: [n for n in names if n in ("chromium", "firefox")])
    monkeypatch.setattr(browsers.subprocess, "run", _failed_download)
    monkeypatch.delenv("WEB_UI_CHROMIUM", raising=False)
    return monkeypatch


def test_the_computers_chromium_stands_in_when_the_download_fails(offline, tmp_path: Path) -> None:
    chrome = tmp_path / "chrome"
    chrome.write_text("")
    offline.setattr(browsers, "PREINSTALLED_CHROMIUM", [chrome])
    assert browsers.ensure_browsers(["chromium"]) == ""
    assert browsers.launch_options("chromium") == {"executable_path": str(chrome)}
    assert browsers.launch_options("firefox") == {} and browsers.launch_options("webkit") == {}


def test_other_browsers_that_cannot_be_downloaded_are_still_reported(offline, tmp_path: Path) -> None:
    chrome = tmp_path / "chrome"
    chrome.write_text("")
    offline.setattr(browsers, "PREINSTALLED_CHROMIUM", [chrome])
    problem = browsers.ensure_browsers(["chromium", "firefox"])
    assert problem.startswith("Could not install firefox.") and "chromium" not in problem


def test_without_a_stand_in_the_run_says_what_to_install(offline, tmp_path: Path) -> None:
    offline.setattr(browsers, "PREINSTALLED_CHROMIUM", [tmp_path / "absent"])
    assert browsers.ensure_browsers(["chromium"]).startswith("Could not install chromium. Run: python -m playwright install")
    assert browsers.launch_options("chromium") == {}


def _a_real_chromium() -> str:
    """Playwright's Chromium, or its headless build when only that one is installed."""
    with sync_playwright() as p:
        path = Path(p.chromium.executable_path)
    if path.exists():
        return str(path)
    shells = sorted(path.parents[2].glob("chromium_headless_shell-*/*/chrome-headless-shell*"))
    assert shells, f"no Chromium under {path.parents[2]}"
    return str(shells[-1])


def test_the_stand_in_is_used_for_pages_and_phones(tmp_path: Path, site) -> None:  # noqa: ANN001 - ScenarioSite
    """A stand-in that doesn't exist makes every Chromium launch fail, naming it: so both the page checks and the
    phone check really use it. A real one runs the audit as usual."""
    cfg = base_config(site.url, artifacts={"video": "off"}, audit={"max_pages": 2, "check_external_links": False})
    absent = str(tmp_path / "no-such-chrome")
    run = invoke_cli(tmp_path / "absent", ["site_audit", "-k", "crawl or mobile"], config=cfg,
                     env={"WEB_UI_CHROMIUM": absent})
    for name in ("test_crawl_found_the_site", "test_works_on_mobile_devices"):
        t = run.test(name)
        assert t["outcome"] in ("failed", "error") and absent in t["message"] + t.get("details", ""), (name, t)

    run = invoke_cli(tmp_path / "real", ["site_audit", "-k", "crawl or mobile"], config=cfg,
                     env={"WEB_UI_CHROMIUM": _a_real_chromium()})
    assert run.test("test_crawl_found_the_site")["outcome"] == "passed", run.output
    assert run.test("test_works_on_mobile_devices")["outcome"] in ("passed", "failed"), run.output  # it ran


def test_in_claude_code_on_the_web_the_hosts_to_allow_are_named(offline, tmp_path: Path) -> None:
    offline.setattr(browsers, "PREINSTALLED_CHROMIUM", [tmp_path / "absent"])
    offline.setenv("CLAUDE_CODE_REMOTE", "true")
    problem = browsers.ensure_browsers(["firefox"])
    assert problem.endswith("network access must allow cdn.playwright.dev and playwright.download.prss.microsoft.com")
    offline.delenv("CLAUDE_CODE_REMOTE")
    assert "network access" not in browsers.ensure_browsers(["firefox"])
