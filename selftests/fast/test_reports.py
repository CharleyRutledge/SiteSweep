"""The phone report: its summary line and jump list, and the tags a test's name is broken into."""

from __future__ import annotations

import pytest

from ui_automation.reporting.summary import RunSummary


def test_status_includes_errors():
    assert "2 errors" in RunSummary(exit_status=1, errors=2).short_status()


@pytest.mark.parametrize(
    "name, tags",
    [
        ("test_x[-chromium]", ["chromium"]),
        ("test_x[/-chromium]", ["/", "chromium"]),
        ("test_x[chromium-saucedemo]", ["saucedemo", "chromium"]),
        ("test_x[chromium-wrong username]", ["wrong username", "chromium"]),
        ("test_x[/docs/intro-firefox]", ["/docs/intro", "firefox"]),
        ("test_x[webkit]", ["webkit"]),
        ("test_x[base_url_without_scheme]", ["base url without scheme"]),
        ("test_x", []),
    ],
)
def test_variant_tags(name: str, tags: list[str]) -> None:
    from ui_automation.reporting.summary import TestResult

    assert TestResult(f"tests/t.py::{name}", "passed").variant_tags == tags


def _failed_and_passed() -> list:
    from ui_automation.reporting.summary import TestResult

    return [
        TestResult("site_audit/test_site_audit.py::test_served_securely[public-chromium]", "failed", 12.0,
                   "http://example.ie/ does not redirect to https://"),
        TestResult("site_audit/test_site_audit.py::test_website_requirements[public-chromium]", "failed", 9.0,
                   "no privacy notice"),
        TestResult("site_audit/test_site_audit.py::test_pages_load[public-chromium]", "passed", 3.0),
    ]


def test_the_report_names_what_failed_and_links_to_each_failure() -> None:
    """A reader sees which checks failed straight away, and can jump to one however long the page is."""
    from ui_automation.reporting.report_html import render_summary_html

    html = render_summary_html(RunSummary(exit_status=1, passed=1, failed=2, duration=90.0, tests=_failed_and_passed()))
    assert "2 of 3 tests failed: Served securely, Website requirements." in html
    for i in (1, 2):
        assert f'href="#problem-{i}"' in html and f'id="problem-{i}"' in html
    assert 'id="top"' in html  # where "Back to top" goes
    assert "Where the time went" in html  # slowest checks, on a run long enough to care


def test_one_failure_needs_no_jump_list_and_a_quick_run_no_timings() -> None:
    from ui_automation.reporting.report_html import render_summary_html

    html = render_summary_html(RunSummary(exit_status=1, failed=1, duration=5.0, tests=_failed_and_passed()[:1]))
    assert 'nav class="jump"' not in html
    assert "Where the time went" not in html
