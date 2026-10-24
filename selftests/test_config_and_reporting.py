from __future__ import annotations

import pytest

from ui_automation.config import load_settings
from ui_automation.reporting.summary import RunSummary


def _load(tmp_path, text: str):
    p = tmp_path / "s.yaml"
    p.write_text(text, encoding="utf-8")
    return load_settings(p)


def test_env_substituted_false_is_false(tmp_path, monkeypatch):
    monkeypatch.setenv("H", "false")
    s = _load(tmp_path, 'base_url: http://x\nheadless: "${H}"\n')
    assert s.headless is False


@pytest.mark.parametrize(
    "text",
    [
        pytest.param("base_url: example.com\n", id="base_url_without_scheme"),
        pytest.param("base_url: http://x\ntimeout_ms: -5\n", id="negative_timeout"),
        pytest.param("base_url: http://x\nslow_mo_ms: abc\n", id="non_numeric_slow_mo"),
        pytest.param("base_url: http://x\nartifacts: on\n", id="artifacts_not_a_mapping"),
        pytest.param("base_url: http://x\nviewport: 5\n", id="viewport_not_a_mapping"),
        pytest.param("base_url: http://x\nheadless: maybe\n", id="headless_not_a_boolean"),
        pytest.param("- a\n", id="root_is_a_list"),
    ],
)
def test_invalid_config_raises_value_error(tmp_path, text):
    with pytest.raises(ValueError):
        _load(tmp_path, text)


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
