"""Safe security checks (ui_automation/security.py) against real local web servers: one set up well, one with
every problem planted (software versions in its headers, a login cookie without protection, its .git folder and
.env file public, a browsable folder, a loose CORS setting, plain-http files on an HTTPS page). Every planted
problem must be found and nothing on the good server; a "not found" page that answers 200 must never count as
a private file, and private files' contents must never reach the results."""

from __future__ import annotations

import ssl
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Iterator

import pytest
from playwright.sync_api import sync_playwright

from test_firefox_profile import _authority
from ui_automation import security

SECRET = "DB_PASSWORD=hunter2-very-secret"
GOOD_HEADERS = {"Strict-Transport-Security": "max-age=31536000", "X-Content-Type-Options": "nosniff",
                "Referrer-Policy": "strict-origin-when-cross-origin",
                "Content-Security-Policy": "default-src 'self'; frame-ancestors 'none'",
                "Permissions-Policy": "camera=()"}
BAD_HEADERS = {"X-Powered-By": "PHP/7.4.3"}


def _site(bad: bool, mixed_from: str = "") -> dict[str, tuple[int, str, str]]:
    """path -> (status, content type, body)."""
    home = ('<!doctype html><html lang="en"><title>Shop</title><h1>Shop</h1>'
            '<script src="/assets/js/app.js"></script>'
            + (f'<img src="{mixed_from}/logo.png" alt="Logo"><form action="{mixed_from}/subscribe"></form>'
               if mixed_from else ""))
    pages = {"/": (200, "text/html", home), "/assets/js/app.js": (200, "text/javascript", "1;")}
    if bad:
        pages.update({
            "/.git/HEAD": (200, "text/plain", "ref: refs/heads/main\n"),
            "/.env": (200, "text/plain", f"{SECRET}\nAPI_KEY=abc123\n"),
            "/assets/js/": (200, "text/html", "<html><head><title>Index of /assets/js</title></head>"
                                              '<body><a href="app.js">app.js</a></body></html>'),
        })
    else:
        pages["/.well-known/security.txt"] = (200, "text/plain", "Contact: mailto:security@example.ie\n")
    return pages


def _serve(bad: bool, cert: tuple[Path, Path] | None = None, mixed_from: str = "") -> Iterator[str]:
    pages = _site(bad, mixed_from)

    class Handler(BaseHTTPRequestHandler):
        server_version, sys_version = ("Apache/2.4.41", "(Ubuntu)") if bad else ("web", "")

        def do_GET(self) -> None:  # noqa: N802
            path = self.path.split("?")[0]
            # The bad site answers 200 with a page for everything (a "soft 404"), as many sites do.
            status, kind, body = pages.get(path, (200 if bad else 404, "text/html",
                                                  "<!doctype html><title>Not found</title><h1>Page not found</h1>"))
            self.send_response(status)
            self.send_header("Content-Type", kind)
            for k, v in (BAD_HEADERS if bad else GOOD_HEADERS).items():
                self.send_header(k, v)
            if path == "/":
                self.send_header("Set-Cookie", "sessionid=abc; Path=/" if bad else
                                 f"sessionid=abc; Path=/; HttpOnly; SameSite=Lax{'; Secure' if cert else ''}")
                self.send_header("Set-Cookie", "csrftoken=x; Path=/; SameSite=Lax" + ("; Secure" if cert else ""))
            origin = self.headers.get("Origin")
            if bad and origin:
                self.send_header("Access-Control-Allow-Origin", origin)
                self.send_header("Access-Control-Allow-Credentials", "true")
            self.end_headers()
            self.wfile.write(body.encode())

        def log_message(self, *args) -> None:  # noqa: ANN002
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    if cert:
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(*cert)
        server.socket = context.wrap_socket(server.socket, server_side=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield f"{'https' if cert else 'http'}://{'localhost' if cert else '127.0.0.1'}:{server.server_address[1]}/"
    finally:
        server.shutdown()
        server.server_close()


def _audit(home: str, **kw) -> security.Results:  # noqa: ANN003
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            context = browser.new_context(ignore_https_errors=True)
            page = context.new_page()
            return security.audit(context.request, page, home, [home], **kw)
        finally:
            browser.close()


def _by_check(results: security.Results) -> dict[str, security.Finding]:
    found: dict[str, security.Finding] = {}
    for f in results.findings:
        if f.check not in found or f.fails:
            found[f.check] = f
    return found


@pytest.fixture
def no_proxy(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy"):
        monkeypatch.delenv(name, raising=False)


def test_a_well_set_up_site_has_no_findings(no_proxy: None) -> None:
    for home in _serve(bad=False):
        results = _audit(home)
    failed = {f.check: f.detail for f in results.findings if f.fails}
    assert failed == {"https": "the site is not served over HTTPS"}, failed  # a local test server has no HTTPS
    found = _by_check(results)
    assert found["security_txt"].severity == "ok"
    assert found["exposed_files"].detail == "None of 7 well-known private files is public."
    assert found["cors"].severity == "ok" and found["versions"].severity == "ok"
    cookies = {row[0]: row for row in results.tables[1]["rows"]}
    assert cookies["sessionid"][3:] == ["yes", "Lax", "fine"]
    assert cookies["csrftoken"][5] == "fine"  # meant to be read by the page's scripts: no HttpOnly needed


def test_every_planted_problem_is_found(no_proxy: None) -> None:
    for home in _serve(bad=True):
        results = _audit(home, api=[home + "api/orders"])
    found = _by_check(results)
    assert found["versions"].severity == "low"
    assert "Server: Apache/2.4.41 (Ubuntu)" in found["versions"].detail
    assert "X-Powered-By: PHP/7.4.3" in found["versions"].detail
    assert found["cookies"].severity == "medium" and "sessionid: no HttpOnly, no SameSite" in found["cookies"].detail
    exposed = [f for f in results.findings if f.check == "exposed_files"]
    assert sorted(f.detail.split(" ")[0] for f in exposed) == ["/.env", "/.git/HEAD"]
    assert all(f.severity == "high" for f in exposed)
    assert found["directory_listing"].detail == "These folders list their files: /assets/js/."
    assert found["cors"].severity == "high" and "with the visitor's login" in found["cors"].detail
    assert found["clickjacking"].severity == "medium" and found["hsts"].severity == "medium"
    assert found["security_txt"].severity == "info" and not found["security_txt"].fails


def test_private_files_contents_are_never_shown(no_proxy: None) -> None:
    for home in _serve(bad=True):
        results = _audit(home)
    everything = repr([f.__dict__ for f in results.findings]) + repr(results.tables)
    assert "hunter2" not in everything and "abc123" not in everything
    rows = {row[0]: row[1] for row in results.tables[-1]["rows"]}
    assert rows["/.env"].startswith("PUBLIC (") and rows["/.env"].endswith("bytes; contents not shown)")
    # The soft-404 page answers 200 for every address: only real file contents count.
    assert rows["/.htpasswd"] == rows["/phpinfo.php"] == "not public (HTTP 200)"


def test_https_site_checks_cookies_mixed_content_and_the_certificate(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch, no_proxy: None) -> None:
    ca, cert, key = _authority(tmp_path / "ca", "SiteSweep test authority")
    monkeypatch.setenv("SSL_CERT_FILE", str(ca))  # Python's own checks trust the test authority
    for good in _serve(bad=False, cert=(cert, key)):
        results = _audit(good)
    found = _by_check(results)
    assert found["https"].detail.startswith("Served over HTTPS")
    assert found["certificate"].severity == "medium" and "expires in 1 day(s)" in found["certificate"].detail
    assert found["mixed_content"].severity == "ok" and found["cookies"].severity == "ok"

    for bad in _serve(bad=True, cert=(cert, key), mixed_from="http://127.0.0.1:9"):
        results = _audit(bad)
    found = _by_check(results)
    assert found["cookies"].detail.startswith("sessionid: no Secure, no HttpOnly, no SameSite")
    rows = next(t for t in results.tables if t["title"] == "Loaded or sent over plain http")["rows"]
    assert [r[2] for r in rows] == ["img over http", "form sends over http"], rows

    _, other_cert, other_key = _authority(tmp_path / "other", "Authority nobody trusts")
    for untrusted in _serve(bad=False, cert=(other_cert, other_key)):
        results = _audit(untrusted)
    cert_finding = _by_check(results)["certificate"]
    assert cert_finding.severity == "high" and "not trusted" in cert_finding.detail


def test_behind_a_network_that_re_signs_https_the_certificate_is_not_judged(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ca, cert, key = _authority(tmp_path / "ca", "SiteSweep test authority")
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:9")  # only read, never used for these requests
    for home in _serve(bad=False, cert=(cert, key)):
        results = _audit(home)
    finding = _by_check(results)["certificate"]
    assert finding.severity == "info" and "re-signs HTTPS" in finding.detail


def test_cookie_headers_are_read_exactly() -> None:
    assert security.parse_cookie("id=1; Path=/; Secure; HttpOnly; SameSite=Strict") == {
        "name": "id", "secure": True, "httponly": True, "samesite": "Strict"}
    assert security.parse_cookie("a=b=c")["name"] == "a"


def test_the_site_audit_runs_them_and_reports_each_with_its_standard(tmp_path: Path) -> None:
    from harness import base_config, invoke_cli

    for home in _serve(bad=True):
        cfg = base_config(home.rstrip("/"), artifacts={"video": "off"},
                          audit={"max_pages": 2, "check_external_links": False, "security_checks": "on"})
        run = invoke_cli(tmp_path / "run", ["site_audit", "-k", "crawl or served_securely"], config=cfg)
    t = run.test("test_served_securely")
    assert t["outcome"] == "failed", run.output
    text = t["message"] + t["details"]
    assert "[high] No private files public: /.git/HEAD is public" in text and "(ASVS 4.3.2;" in text
    assert "hunter2" not in text and "hunter2" not in (run.run_dir / "summary.html").read_text(encoding="utf-8")
    assert t["about"].startswith("Safe security checks")
    assert [e["title"] for e in t["evidence"]][0] == "Security checks"


def test_a_public_endpoint_that_repeats_any_origin_is_advice_not_high() -> None:
    """WordPress's public REST API repeats any Origin and allows credentials; with no login cookie there is
    nothing private to read, so it is low. With a login cookie it stays high."""
    from ui_automation import security

    class Reply:
        headers = {"Access-Control-Allow-Origin": security.TEST_ORIGIN, "Access-Control-Allow-Credentials": "true"}

    class Request:
        def __init__(self, cookies: list) -> None:
            self.cookies = cookies

        def storage_state(self) -> dict:
            return {"cookies": self.cookies}

        def get(self, *a, **k):  # noqa: ANN002, ANN003, ANN201
            return Reply()

    public, private = security.Results(), security.Results()
    security._cors(public, Request([]), "https://x.ie/", ["https://x.ie/wp-json/wp/v2/posts"])
    security._cors(private, Request([{"name": "sid"}]), "https://x.ie/", [])
    assert [f.severity for f in public.findings] == ["low"]
    assert [f.severity for f in private.findings] == ["high"]
