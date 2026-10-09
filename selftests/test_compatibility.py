"""Compatibility grid (ui_automation/reporting/compat.py): every check × every browser, the phones, and the
computer and browser versions used; and runs from several computers combined into one grid. Checked through a
real site audit run, and in a real browser at phone width (nothing may need sideways scrolling)."""

from __future__ import annotations

import json
from pathlib import Path

from playwright.sync_api import sync_playwright

from harness import base_config, invoke_cli
from test_site_audit import CLEAN, _serve
from ui_automation.reporting import compat
from ui_automation.reporting.report_html import render_summary_html
from ui_automation.reporting.summary import RunSummary, TestResult

AUDIT = "site_audit/test_site_audit.py::"


def _t(name: str, outcome: str, **kw) -> TestResult:  # noqa: ANN003
    return TestResult(AUDIT + name, outcome, 1.0, **kw)


def test_the_grid_shows_the_worst_result_per_check_and_browser() -> None:
    tests = [_t("test_no_javascript_errors[public-chromium]", "passed"),
             _t("test_no_javascript_errors[admin-chromium]", "failed"),  # one role failing fails the cell
             _t("test_no_javascript_errors[public-webkit]", "passed"),
             _t("test_no_broken_links[public-chromium]", "passed"),  # once per site: first browser only
             _t("test_works_on_mobile_devices[public-chromium]", "passed", evidence=[{
                 "title": compat.PHONES_TITLE, "columns": [], "note": "",
                 "rows": [["iPhone 15", "Safari's engine (WebKit)", "4", "0", "✓ passed"]]}])]
    env = {"os": "Linux 6.1", "browsers": {"chromium": "141.0.7390.37", "webkit": "26.0"}}
    columns, rows, phones = compat.grid([(env, tests)])
    assert columns == ["Chrome's engine (Chromium) 141.0.7390.37", "Safari's engine (WebKit) 26.0"]
    assert ["No javascript errors", "✕ failed", "✓ passed"] in rows
    assert ["No broken links", "✓ passed", ""] in rows
    assert phones == [["iPhone 15", "Safari's engine (WebKit)", "4", "0", "✓ passed"]]


def test_runs_from_several_computers_get_a_column_each() -> None:
    mac = ({"os": "macOS 15.1", "browsers": {"webkit": "26.0"}}, [_t("test_no_javascript_errors[public-webkit]",
                                                                      "failed")])
    linux = ({"os": "Linux 6.1", "browsers": {}}, [_t("test_no_javascript_errors[public-webkit]", "passed")])
    columns, rows, _ = compat.grid([linux, mac])
    assert columns == ["Safari's engine (WebKit) on Linux 6.1", "Safari's engine (WebKit) 26.0 on macOS 15.1"]
    assert rows == [["No javascript errors", "✓ passed", "✕ failed"]]


def test_a_real_run_records_its_computer_and_browsers_and_shows_the_grid(tmp_path: Path) -> None:
    for url in _serve(CLEAN):
        # Browsers and phones the CI machine has (Chromium and Firefox; no WebKit there).
        cfg = base_config(url, artifacts={"video": "off"}, browsers=["chromium", "firefox"], browser_rotation="off",
                          audit={"max_pages": 2, "check_external_links": False,
                                 "mobile_devices": ["Pixel 7", "Galaxy S9+"]})
        run = invoke_cli(tmp_path / "run", ["site_audit", "-k", "crawl or javascript or mobile"], config=cfg)
    data = json.loads((run.run_dir / "summary.json").read_text(encoding="utf-8"))
    env = data["environment"]
    assert env["os"] and "chromium" in env["browsers"], env
    assert all(v[0].isdigit() for v in env["browsers"].values() if v), env  # Firefox's trusted profile: no version
    assert "Firefox" in html_columns(run.run_dir), "a column for each browser that ran"
    html = (run.run_dir / "summary.html").read_text(encoding="utf-8")
    assert "<h2>Compatibility</h2>" in html and f"Chrome&#x27;s engine (Chromium) {env['browsers']['chromium']}" in html
    phones = next(e for t in data["tests"] for e in t["evidence"] if e["title"] == compat.PHONES_TITLE)
    assert [r[0] for r in phones["rows"]] == ["Pixel 7", "Galaxy S9+"], phones
    assert phones["rows"][1][1] == "Chrome's engine (Chromium)"

    # The same site checked on another computer (its summary as that computer wrote it), combined into one grid.
    other = tmp_path / "mac"
    other.mkdir()
    data["environment"] = {"os": "macOS 15.1", "browsers": {"webkit": "26.0"}}
    (other / "summary.json").write_text(json.dumps(data), encoding="utf-8")
    out = tmp_path / "compatibility.html"
    assert compat.main([str(run.run_dir), str(other), "-o", str(out)]) == 0
    combined = out.read_text(encoding="utf-8")
    assert "on macOS 15.1" in combined and f"on {env['os']}" in combined


def html_columns(run_dir: Path) -> str:
    html = (run_dir / "summary.html").read_text(encoding="utf-8")
    return html.split("<h2>Compatibility</h2>", 1)[1].split("</thead>", 1)[0]


def test_the_grid_fits_a_small_phone(tmp_path: Path) -> None:
    tests = [_t(f"test_check_number_{i}[public-{b}]", "passed") for i in range(3) for b in compat.BROWSERS]
    summary = RunSummary(exit_status=0, passed=9, run_dir=tmp_path, tests=tests, name="Grid",
                         environment={"os": "Linux", "browsers": {b: "1.2.3" for b in compat.BROWSERS}})
    page_file = tmp_path / "summary.html"
    page_file.write_text(render_summary_html(summary), encoding="utf-8")
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 320, "height": 800})
        page.goto(page_file.as_uri())
        assert page.locator("table.compat tbody tr").count() == 3
        assert page.evaluate("document.documentElement.scrollWidth") <= 320
        browser.close()


def test_a_missing_run_folder_is_explained(tmp_path: Path, capsys) -> None:  # noqa: ANN001
    assert compat.main([str(tmp_path), "-o", str(tmp_path / "x.html")]) == 2
    assert "no summary.json here" in capsys.readouterr().err
