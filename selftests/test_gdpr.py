"""GDPR and cookie checks (ui_automation/gdpr.py) against real local sites in a real browser: one that does it
right (equal Accept / Reject, nothing before a choice, a full privacy notice, a way to change your mind) and two
that get it wrong in the ways the EDPB cookie banner taskforce lists. Every problem must be found, and nothing
may be reported on the good site. Tracker addresses are blocked by the check itself, so nothing leaves this
computer."""

from __future__ import annotations

import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Iterator

import pytest
from playwright.sync_api import sync_playwright

from harness import base_config, invoke_cli
from ui_automation import gdpr

GA = '<script src="https://www.google-analytics.com/analytics.js"></script>'
NOTICE = """<h1>Privacy notice</h1>
<p>Example Ltd is the controller of your personal data. Our data protection officer (DPO) is at dpo@example.ie.</p>
<p>We use your data for these purposes: answering enquiries and sending the newsletter you asked for.</p>
<p>Legal basis: your consent, and performance of a contract.</p>
<p>Recipients: our email service provider, a processor bound by contract.</p>
<p>Transfers outside the EEA are protected by standard contractual clauses.</p>
<p>Retention: enquiries are kept for 2 years.</p>
<p>You have the right of access, rectification, erasure, to object and to portability.</p>
<p>You can withdraw consent at any time.</p>
<p>You can lodge a complaint with the Data Protection Commission (dataprotection.ie).</p>"""
FOOTER = ('<footer><a href="/privacy">Privacy notice</a> <a href="/contact">Contact</a> '
          '<button id="settings" type="button" onclick="reopen()">Cookie settings</button></footer>')
BANNER = """<div id="cookie-banner" role="dialog" aria-label="Cookies" hidden>
  <p>We'd like to use analytics cookies.</p>
  <button type="button" onclick="choose('accept')" style="padding:10px 20px">Accept all</button>
  <button type="button" onclick="choose('reject')" style="padding:10px 20px">Reject all</button>
</div>
<script>
  const choice = (document.cookie.match(/cookie_consent=(\\w+)/) || [])[1];
  function tracking() {
    document.cookie = '_ga=GA1.1.42.42; max-age=63072000; path=/';
    const s = document.createElement('script'); s.src = 'https://www.google-analytics.com/analytics.js';
    document.head.appendChild(s);
  }
  function choose(c) {
    document.cookie = 'cookie_consent=' + c + '; max-age=15552000; path=/';
    document.getElementById('cookie-banner').hidden = true;
    if (c === 'accept') tracking();
  }
  function reopen() { document.getElementById('cookie-banner').hidden = false; }
  if (!choice) reopen(); else if (choice === 'accept') tracking();
</script>"""


def _page(title: str, body: str) -> str:
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8"><title>{title}</title></head>'
            f"<body><main>{body}</main></body></html>")


GOOD = {
    "/": _page("Home", "<h1>Home</h1>" + BANNER + FOOTER),
    "/contact": _page("Contact", '<h1>Contact</h1><form action="/send" method="post"><label>Email '
                                 '<input type="email" name="email"></label><label><input type="checkbox" '
                                 'name="newsletter"> Send me the newsletter</label><button>Send</button></form>'
                                 + BANNER + FOOTER),
    "/privacy": _page("Privacy", NOTICE + BANNER + FOOTER),
}
# Tracking before any choice, only "Accept" on the first screen, a marketing box ticked in advance in the banner,
# a privacy notice that leaves most of Art. 13 out, and a sign-up form with no privacy link and a ticked box.
NO_REJECT = {
    "/": _page("Home", "<h1>Home</h1>" + GA + """
        <script>document.cookie = '_ga=GA1.1.1.1; max-age=63072000; path=/';
                localStorage.setItem('_hjSession', '1');</script>
        <div class="cookie-notice"><p>We use cookies.</p>
          <label><input type="checkbox" checked> Marketing</label>
          <button type="button" style="padding:12px 40px">Accept all</button>
          <a href="#">Manage cookies</a></div>
        <a href="/privacy">Privacy</a> <a href="/signup">Sign up</a>"""),
    "/signup": _page("Sign up", '<h1>Sign up</h1><form action="/join"><input type="email" name="email" '
                                'placeholder="Email"><label><input type="checkbox" checked name="offers"> Send me '
                                'offers from partners</label><button>Join</button></form>'),
    "/privacy": _page("Privacy", "<h1>Privacy</h1><p>We respect your privacy. Contact us with questions.</p>"),
}
# A reject button much smaller than Accept, that doesn't stop tracking, and no way back to the choice afterwards.
TINY_REJECT = {
    "/": _page("Home", "<h1>Home</h1>" + GA + """
        <div id="consent" role="dialog" aria-label="Cookies"><p>Cookies help us.</p>
          <button type="button" style="font-size:20px;padding:20px 80px"
                  onclick="this.parentElement.remove()">Accept all</button>
          <button type="button" style="font-size:9px;padding:0"
                  onclick="document.cookie='cookie_consent=reject;path=/';this.parentElement.remove()">Reject</button>
        </div><a href="/privacy">Privacy</a>"""),
    "/privacy": _page("Privacy", NOTICE),
}


def _serve(pages: dict[str, str]) -> Iterator[str]:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            body = pages.get(self.path.split("?")[0])
            self.send_response(200 if body else 404)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write((body or _page("Not found", "<h1>Not found</h1>")).encode())

        def log_message(self, *args) -> None:  # noqa: ANN002
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()


def _audit(pages: dict[str, str], paths: list[str]) -> tuple[dict[str, gdpr.CheckResult], gdpr.Findings]:
    for url in _serve(pages):
        with sync_playwright() as p:
            browser = p.chromium.launch()
            try:
                found = gdpr.audit(browser, [url + path for path in paths])
            finally:
                browser.close()
    return {r.check: r for r in found.results}, found


def _table(found: gdpr.Findings, starts: str) -> dict:
    return next(t for t in found.tables if t["title"].startswith(starts) or starts in t["title"])


def test_a_site_that_does_it_right_passes_every_check() -> None:
    results, found = _audit(GOOD, ["/", "/contact"])
    assert set(results) == {"no_tracking_before_consent", "reject_as_easy", "no_pre_ticked", "reject_works",
                            "change_your_mind", "outside_eu_before_consent", "privacy_notice_content", "forms"}
    failed = {k: r.detail for k, r in results.items() if not r.passed}
    assert not failed, failed
    assert results["reject_as_easy"].detail == '"Reject all" is on the first screen, as easy as "Accept all".'
    assert results["change_your_mind"].detail == '"Cookie settings" stays available after choosing.'
    cookies = {row[0]: row for row in _table(found, "cookie(s) seen")["rows"]}
    # _ga only after Accept (asked for 2 years; Chrome keeps cookies 400 days at most); the choice cookie after
    # either choice and never before.
    assert cookies["_ga"][2:] == ["tracking", "400 day(s)", "no", "no", "yes"], cookies
    assert cookies["cookie_consent"][2] == "remembers the cookie choice"
    assert cookies["cookie_consent"][4:] == ["no", "yes", "yes"]
    others = {row[0]: row for row in _table(found, "other site(s) contacted")["rows"]}
    assert others["www.google-analytics.com"][1:] == ["Google", "USA", "no", "no", "yes", "yes"]
    notice = _table(found, "What the privacy notice covers")["rows"]
    assert len(notice) == 10 and all(row[1] == "yes" for row in notice), notice


def test_tracking_before_a_choice_and_no_reject_button_are_found() -> None:
    results, found = _audit(NO_REJECT, ["/", "/signup"])
    early = results["no_tracking_before_consent"]
    assert not early.passed
    for item in ("cookie _ga (127.0.0.1)", "stored item _hjSession", "request to www.google-analytics.com"):
        assert item in early.detail, early.detail
    assert "ePrivacy Regulations 2011" in early.law
    assert not results["reject_as_easy"].passed
    assert results["reject_as_easy"].detail == 'The banner offers "Accept all" but no reject button on the same screen.'
    assert results["no_pre_ticked"].detail == "Ticked in advance: Marketing."
    assert results["outside_eu_before_consent"].detail == "Before any choice, requests went to: Google (USA)."
    notice = results["privacy_notice_content"]
    assert not notice.passed and "The legal basis for each use" in notice.detail
    assert "The right to complain to the Data Protection Commission" in notice.detail
    assert not results["forms"].passed
    form = _table(found, "Forms that collect personal data")["rows"][0]
    assert form[0] == "/signup" and form[1] == "email" and form[3] == "no"
    assert form[4] == "Send me offers from partners"
    assert "reject_works" not in results  # nothing to press, so nothing to test after it


def test_a_reject_button_that_is_hard_to_see_and_does_nothing_is_found() -> None:
    results, _ = _audit(TINY_REJECT, ["/"])
    easy = results["reject_as_easy"]
    assert not easy.passed and easy.detail.startswith('"Reject" is much smaller than "Accept all"'), easy.detail
    works = results["reject_works"]
    assert not works.passed and works.detail == 'After "Reject": request to www.google-analytics.com.'
    assert not results["change_your_mind"].passed
    assert results["privacy_notice_content"].passed


def test_the_site_audit_runs_it_and_reports_what_it_found(tmp_path) -> None:  # noqa: ANN001
    for url in _serve(NO_REJECT):
        cfg = base_config(url, artifacts={"video": "off"}, compliance={"enabled": True, "gdpr_pages": 2},  # /, /signup
                          audit={"max_pages": 5, "check_external_links": False})
        run = invoke_cli(tmp_path / "run", ["site_audit", "-k", "crawl or gdpr"], config=cfg)
    t = run.test("test_follows_gdpr_and_cookie_rules")
    assert t["outcome"] == "failed", run.output
    assert "GDPR or cookie rule(s) not followed" in t["message"]
    assert t["about"].startswith("GDPR and cookie rules")
    titles = [e["title"] for e in t["evidence"]]
    assert titles[0] == "GDPR and cookie checks" and "Forms that collect personal data" in titles, titles
    assert [r["title"] for r in t["compliance"][0]["results"] if not r["passed"]][:2] == [
        "No tracking before you choose", "Rejecting is as easy as accepting"]
    html = (run.run_dir / "summary.html").read_text(encoding="utf-8")
    assert "GDPR and cookies (2 page(s))" in html and "CJEU Planet49" in html


def test_it_can_be_turned_off(tmp_path) -> None:  # noqa: ANN001
    for url in _serve(GOOD):
        cfg = base_config(url, artifacts={"video": "off"}, compliance={"enabled": True, "gdpr": False},
                          audit={"max_pages": 1, "check_external_links": False})
        run = invoke_cli(tmp_path / "run", ["site_audit", "-k", "crawl or gdpr"], config=cfg)
    assert "Follows GDPR and cookie rules: compliance.gdpr is false" in run.output


@pytest.mark.parametrize("host, site", [("www.shop.example.ie", "example.ie"), ("a.example.co.uk", "example.co.uk"),
                                        ("127.0.0.1", "127.0.0.1"), ("localhost", "localhost")])
def test_cookies_are_matched_to_the_site_that_owns_them(host: str, site: str) -> None:
    assert gdpr._site(host) == site
    assert not gdpr._same_site("notexample.ie", "www.example.ie")


def test_pages_that_ask_for_personal_data_are_visited_first() -> None:
    crawl = [f"https://x.ie{p}" for p in ("/", "/about", "/privacy-policy", "/blog", "/contact-us", "/newsletter")]
    assert gdpr.pick_pages(crawl, 3) == ["https://x.ie/", "https://x.ie/contact-us", "https://x.ie/newsletter"]
    assert gdpr.pick_pages(crawl, 9)[3:] == ["https://x.ie/about", "https://x.ie/blog"]
