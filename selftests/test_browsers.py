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
    for name in ("WEB_UI_CHROMIUM", "HTTPS_PROXY", "https_proxy"):
        monkeypatch.delenv(name, raising=False)
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
    """A stand-in that doesn't exist can't start, so the run stops before testing and names it. A real one runs the
    page checks and the phone check as usual."""
    cfg = base_config(site.url, artifacts={"video": "off"}, audit={"max_pages": 2, "check_external_links": False})
    absent = str(tmp_path / "no-such-chrome")
    run = invoke_cli(tmp_path / "absent", ["site_audit", "-k", "crawl or mobile"], config=cfg,
                     env={"WEB_UI_CHROMIUM": absent})
    assert run.returncode == 2 and run.run_dir is None, run.output
    assert "No browser can test this site on this computer" in run.output and absent in run.output

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


def test_a_browser_that_cannot_work_here_is_left_out_and_listed(tmp_path: Path, site) -> None:  # noqa: ANN001
    """browsers: [chromium, firefox] where Chromium can't start: the run goes on in Firefox, the phone that runs in
    Chromium is left out too, and both are listed under "Not run" instead of every test failing the same way."""
    if browsers.missing_browsers(["firefox"]):
        pytest.skip("Firefox is not installed here (CI installs it: python -m playwright install firefox)")
    cfg = base_config(site.url, browsers=["chromium", "firefox"], browser_rotation="off", artifacts={"video": "off"},
                      audit={"max_pages": 2, "check_external_links": False})
    run = invoke_cli(tmp_path, ["site_audit", "-k", "crawl or mobile"], config=cfg,
                     env={"WEB_UI_CHROMIUM": str(tmp_path / "no-such-chrome")})
    ids = {t["nodeid"].split("::")[1] for t in run.summary["tests"]}
    assert ids == {"test_crawl_found_the_site[public-firefox]", "test_works_on_mobile_devices[public-firefox]"}, ids
    assert run.test("test_crawl_found_the_site")["outcome"] == "passed", run.output
    assert run.output.count("In Chrome's engine (Chromium): could not start") == 1, run.output  # the Not run list
    assert "Not run in Chrome's engine (Chromium): could not start" in run.output


class _Problems:
    def __init__(self, answers: dict[str, list[str]]) -> None:
        self.answers = answers

    def __call__(self, name: str, url: str) -> str:
        return self.answers[name].pop(0)


def test_each_reason_a_browser_cannot_work_is_told_plainly(monkeypatch: pytest.MonkeyPatch) -> None:
    installs: list[list[str]] = []
    monkeypatch.setattr(browsers.subprocess, "run", lambda cmd, **kw: installs.append(cmd))
    monkeypatch.setattr(browsers.sys, "platform", "linux")
    monkeypatch.setattr(browsers.os, "geteuid", lambda: 0, raising=False)
    deps = "Host system is missing dependencies to run browsers. Missing libraries: libgtk-4.so.1"
    monkeypatch.setattr(browsers, "_try", _Problems({
        "chromium": [""],
        "webkit": [deps, ""],  # fixed by installing the system libraries
        "firefox": ["Page.goto: SEC_ERROR_UNKNOWN_ISSUER"],
    }))
    usable, why_not = browsers.usable_browsers(["chromium", "webkit", "firefox"], "https://example.ie")
    assert usable == ["chromium", "webkit"]
    assert installs and installs[0][-2:] == ["install-deps", "webkit"]
    assert why_not == ["Firefox: it doesn't trust the certificate of this computer's network proxy, so it can't open "
                       "HTTPS sites here (it works on a computer without that proxy, e.g. your own)"]

    monkeypatch.setattr(browsers.os, "geteuid", lambda: 1000, raising=False)  # not allowed to install
    monkeypatch.setattr(browsers, "_try", _Problems({"webkit": [deps]}))
    assert browsers.usable_browsers(["webkit"], "https://example.ie") == (
        [], ["Safari's engine (WebKit): this computer is missing system libraries it needs "
             "(run: sudo python -m playwright install-deps webkit)"])


def test_the_proxy_is_given_to_every_browser_and_request(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("https_proxy", raising=False)
    monkeypatch.delenv("no_proxy", raising=False)
    monkeypatch.delenv("WEB_UI_CHROMIUM", raising=False)
    monkeypatch.delenv("HTTPS_PROXY", raising=False)
    assert browsers.proxy_settings() is None and browsers.launch_options("firefox") == {}
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:3128")
    monkeypatch.setenv("NO_PROXY", "pypi.org, .internal, 10.0.0.0/8, ::1")
    proxy = {"server": "http://127.0.0.1:3128", "bypass": "localhost,127.0.0.1,pypi.org,.internal"}
    assert browsers.proxy_settings() == proxy  # CIDR ranges and IPv6 left out: not every browser reads them
    assert browsers.launch_options("webkit") == {"proxy": proxy}
