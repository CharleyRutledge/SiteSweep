"""The phone report explains every check and shows what it found: a "What this checks" line, evidence tables
(failed request, broken link, load time per page...) for passed and failed checks, the reported problems as a list
instead of a traceback, and accessibility issues grouped by problem with who they affect. Checked in a real
browser at phone width (nothing may need sideways scrolling)."""

from __future__ import annotations

from pathlib import Path
from typing import Iterator

import pytest
from playwright.sync_api import Page, expect, sync_playwright

from ui_automation.reporting.report_html import render_summary_html
from ui_automation.reporting.summary import RunSummary, TestResult

LONG = "https://cdn.example.ie/" + "a" * 400 + ".js"  # an address far wider than a phone


def _report(tmp_path: Path) -> Path:
    network = TestResult(
        "site_audit/test_site_audit.py::test_no_network_errors[public-chromium]", "failed", 1.0,
        message="AssertionError: 2 failed network request(s):",
        details="E   AssertionError: 2 failed network request(s):\nE   - /contact/: GET /a.js -> HTTP 404\n",
        about="Everything a page loads arrives.",
        evidence=[{"title": "2 failed request(s) on 3 page(s) checked", "columns": ["Page", "Request", "Result"],
                   "rows": [["/contact/", "GET /a.js", "HTTP 404"], ["/", f"GET {LONG}", "no answer"]],
                   "note": "HTTP 4xx: the file or address doesn't exist."}])
    links = TestResult(
        "site_audit/test_site_audit.py::test_no_broken_links[public-chromium]", "failed", 2.0,
        message="AssertionError: 1 broken link(s):",
        details="E   AssertionError: 1 broken link(s):\nE   - https://x.ie/old (linked from /about/): HTTP 404\n")
    speed = TestResult(
        "site_audit/test_site_audit.py::test_pages_load_quickly[public-chromium]", "passed", 0.5,
        about="How long each page takes until it can be used.",
        evidence=[{"title": "0 of 2 page(s) slower than the limit of 3000 ms",
                   "columns": ["Page", "Usable after", "Within the limit?"],
                   "rows": [["/", "1.2 s", "yes"], ["/about/", "0.8 s", "yes"]], "note": ""}])
    issue = {"rule": "color-contrast", "impact": "serious", "help": "Text must have enough contrast",
             "description": "Ensures the contrast between text and background is high enough",
             "affects": ["people with low vision or colour blindness"], "criteria": ["1.4.3"],
             "help_url": "https://dequeuniversity.com/rules/axe/4.13/color-contrast", "count": 2,
             "targets": ["footer p"], "fixes": [{"target": "footer p", "html": "<p>", "fix": "color: #595959;"}]}
    a11y = TestResult("site_audit/test_site_audit.py::test_pages_are_accessible[public-chromium]", "passed", 1.0,
                      accessibility=[{"url": f"http://app/{p}", "standard": "wcag21aa", "violations": [issue]}
                                     for p in ("", "about/", "contact/")])
    summary = RunSummary(exit_status=1, passed=2, failed=2, run_dir=tmp_path, tests=[network, links, speed, a11y],
                         base_url="http://app", duration=4.0, name="Evidence test")
    path = tmp_path / "summary.html"
    path.write_text(render_summary_html(summary), encoding="utf-8")
    return path


@pytest.fixture
def page(tmp_path: Path) -> Iterator[Page]:
    with sync_playwright() as p:
        browser = p.chromium.launch()
        pg = browser.new_page(viewport={"width": 320, "height": 800})
        pg.goto(_report(tmp_path).as_uri())
        yield pg
        browser.close()


def test_a_failed_check_explains_itself_and_shows_its_evidence(page: Page) -> None:
    card = page.locator(".card.fail", has_text="No network errors")
    expect(card).to_contain_text("What this checks: Everything a page loads arrives.")
    expect(card.locator("table.evidence tbody tr")).to_have_count(2)
    expect(card).to_contain_text("/contact/")
    expect(card).to_contain_text("HTTP 404")
    expect(card.locator(".msg")).to_have_text("2 failed network request(s):")  # no "AssertionError"
    expect(card.get_by_text("Technical details (for developers)")).to_be_visible()


def test_without_evidence_the_reported_problems_are_listed(page: Page) -> None:
    card = page.locator(".card.fail", has_text="No broken links")
    expect(card.locator("ul.problems li")).to_have_text(["https://x.ie/old (linked from /about/): HTTP 404"])


def test_a_passed_check_still_shows_what_was_measured(page: Page) -> None:
    row = page.locator("ul.tests li", has_text="Pages load quickly")
    row.get_by_text("What was checked").click()
    expect(row).to_contain_text("How long each page takes until it can be used.")
    expect(row.locator("table.evidence tbody tr")).to_have_count(2)
    expect(row).to_contain_text("1.2 s")


def test_accessibility_issues_are_grouped_and_explained(page: Page) -> None:
    cards = page.locator(".card", has_text="Text must have enough contrast")
    expect(cards).to_have_count(1)  # one card for the problem, not one per page
    card = cards.first
    expect(card).to_contain_text("Makes the page very hard to use")
    expect(card).to_contain_text("What is wrong: Ensures the contrast")
    expect(card).to_contain_text("Who it affects: people with low vision or colour blindness.")
    expect(card).to_contain_text("Where: 3 page(s): /, /about/, /contact/.")
    expect(card).to_contain_text("probably one fix in a shared header, footer or style")
    expect(card.locator("pre.code")).to_contain_text("color: #595959;")


def test_nothing_needs_sideways_scrolling_on_a_small_phone(page: Page) -> None:
    assert page.evaluate("document.documentElement.scrollWidth") <= 320
    # Each table row is stacked, with every value labelled.
    label = page.locator("table.evidence td").first.evaluate("e => getComputedStyle(e, '::before').content")
    assert "Page" in label
