"""Firefox that trusts what the computer trusts (ui_automation/firefox_profile.py), for networks that re-sign HTTPS
with their own certificate authority (Claude Code on the web). Checked against a real HTTPS server signed by a test
authority: Firefox refuses it on its own, opens it with the computer's list, and still refuses a certificate from
an authority the computer doesn't trust. Each session stays separate, so roles can't see each other's logins."""

from __future__ import annotations

import shutil
import ssl
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Iterator

import pytest
from playwright.sync_api import Error as PlaywrightError, sync_playwright

from harness import base_config, invoke_cli
from test_login_roles import ENV as LOGINS, App, outcomes, roles_config
from ui_automation import browsers, firefox_profile


def _needs(*tools: str) -> None:
    if browsers.missing_browsers(["firefox"]):
        pytest.skip("Firefox is not installed here (CI installs it: python -m playwright install firefox)")
    for tool in tools:
        if not shutil.which(tool):
            pytest.skip(f"{tool} is not installed here (CI installs it: apt-get install libnss3-tools)")


def _authority(folder: Path, name: str) -> tuple[Path, Path, Path]:
    """A test certificate authority and a certificate it signs for localhost: (authority, certificate, key)."""
    folder.mkdir()
    ca, ca_key, cert, key, csr = (folder / n for n in ("ca.pem", "ca.key", "cert.pem", "cert.key", "cert.csr"))
    ext = folder / "ext.cnf"
    ext.write_text("subjectAltName=DNS:localhost\nbasicConstraints=CA:FALSE\nextendedKeyUsage=serverAuth\n")
    run = lambda *args: subprocess.run(["openssl", *args], check=True, capture_output=True)  # noqa: E731
    run("req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", str(ca_key), "-out", str(ca), "-days", "2",
        "-subj", f"/CN={name}", "-addext", "basicConstraints=critical,CA:TRUE",
        "-addext", "keyUsage=critical,keyCertSign,cRLSign")
    run("req", "-newkey", "rsa:2048", "-nodes", "-keyout", str(key), "-out", str(csr), "-subj", "/CN=localhost")
    run("x509", "-req", "-in", str(csr), "-CA", str(ca), "-CAkey", str(ca_key), "-CAcreateserial", "-out", str(cert),
        "-days", "2", "-extfile", str(ext))
    return ca, cert, key


def _https(cert: Path, key: Path) -> Iterator[str]:
    class Page(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(b'<!doctype html><html lang="en"><title>Secure shop</title><h1>Secure shop</h1>')

        def log_message(self, *args) -> None:  # noqa: ANN002
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Page)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(cert, key)
    server.socket = context.wrap_socket(server.socket, server_side=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield f"https://localhost:{server.server_address[1]}/"
    finally:
        server.shutdown()
        server.server_close()


def _title(browser, url: str) -> str:  # noqa: ANN001
    page = browser.new_page()
    try:
        page.goto(url, timeout=15_000)
        return page.title()
    except PlaywrightError as exc:
        return str(exc).splitlines()[0]


def test_firefox_trusts_the_computers_authorities_and_still_checks_certificates(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _needs("certutil", "openssl")
    trusted_ca, cert, key = _authority(tmp_path / "trusted", "SiteSweep test authority")
    _, other_cert, other_key = _authority(tmp_path / "other", "Authority the computer does not trust")
    monkeypatch.setenv("SSL_CERT_FILE", str(trusted_ca))  # the computer's list: just the test authority
    profile = firefox_profile.build_profile()
    assert profile and (Path(profile) / "cert9.db").exists()
    for good in _https(cert, key):
        for bad in _https(other_cert, other_key):
            with sync_playwright() as p:
                plain = p.firefox.launch(**browsers.launch_options("firefox"))
                assert "SEC_ERROR_UNKNOWN_ISSUER" in _title(plain, good)  # Firefox alone: its own list only
                plain.close()
                trusted = firefox_profile.ProfileBrowser(p.firefox, {"headless": True,
                                                                     **browsers.launch_options("firefox")}, profile)
                assert _title(trusted, good) == "Secure shop"
                assert "SEC_ERROR_UNKNOWN_ISSUER" in _title(trusted, bad)  # checking is still on
                trusted.close()


def test_each_session_is_separate_and_takes_a_saved_login(tmp_path: Path) -> None:
    _needs("certutil")
    template = tmp_path / "profile"
    template.mkdir()
    subprocess.run(["certutil", "-N", "--empty-password", "-d", f"sql:{template}"], check=True)
    app = App()
    try:
        with sync_playwright() as p:
            browser = firefox_profile.ProfileBrowser(p.firefox, {"headless": True}, str(template))
            admin = browser.new_context(storage_state={"cookies": [
                {"name": "sid", "value": "admin-session", "domain": "127.0.0.1", "path": "/", "expires": -1,
                 "httpOnly": False, "secure": False, "sameSite": "Lax"}],
                "origins": [{"origin": app.url, "localStorage": [{"name": "role", "value": "admin"}]}]})
            visitor = browser.new_context()
            page = admin.new_page()
            page.goto(app.url + "/login")
            assert page.evaluate("localStorage.getItem('role')") == "admin"
            assert [c["value"] for c in admin.cookies()] == ["admin-session"]
            assert visitor.cookies() == []  # nothing of the admin's session reaches another one
            assert len(admin.pages) == 1  # the browser's own blank tab was reused, not left open
            browser.close()
            assert browser.contexts == []
    finally:
        app.server.shutdown()


def test_roles_stay_apart_in_the_trusted_firefox(tmp_path: Path) -> None:
    """The whole audit with roles, in Firefox with the trusted profile: permission checks still pass where the app
    refuses, and still find a permission hole."""
    _needs("certutil")
    template = tmp_path / "profile"
    template.mkdir()
    subprocess.run(["certutil", "-N", "--empty-password", "-d", f"sql:{template}"], check=True)
    env = {**LOGINS, firefox_profile.ENV: str(template)}
    for hole in (False, True):
        app = App()
        try:
            cfg = roles_config(app.url)
            cfg.update(browsers=["firefox"], audit={**cfg["audit"], "mobile_devices": []})
            cfg["artifacts"] = {"video": "off"}
            if hole:
                cfg["auth"]["roles"][1]["must_not_access"] = ["/admin", "/reports"]  # the app lets viewers see these
            run = invoke_cli(tmp_path / f"hole-{hole}", ["site_audit", "-k", "crawl or refused or api"],
                             config=cfg, env=env)
        finally:
            app.server.shutdown()
        o = outcomes(run)
        assert o["test_role_is_refused_restricted_pages[viewer-firefox]"] == ("failed" if hole else "passed"), run.output
        assert o["test_api_keeps_roles_apart[admin-firefox]"] == "passed", run.output


def test_the_run_switches_firefox_to_the_trusted_profile_only_when_needed(monkeypatch: pytest.MonkeyPatch,
                                                                         tmp_path: Path) -> None:
    monkeypatch.delenv(firefox_profile.ENV, raising=False)
    monkeypatch.setattr(browsers, "proxy_settings", lambda: {"server": "http://127.0.0.1:3128"})
    monkeypatch.setattr(firefox_profile, "build_profile", lambda: str(tmp_path))
    answers = iter(["Page.goto: SEC_ERROR_UNKNOWN_ISSUER", ""])
    monkeypatch.setattr(browsers, "_try", lambda name, url: next(answers))
    assert browsers.usable_browsers(["firefox"], "https://example.ie") == (["firefox"], [])
    assert browsers.os.environ[firefox_profile.ENV] == str(tmp_path)

    monkeypatch.delenv(firefox_profile.ENV)
    answers = iter(["Page.goto: SEC_ERROR_UNKNOWN_ISSUER", "Page.goto: SEC_ERROR_UNKNOWN_ISSUER"])
    usable, why_not = browsers.usable_browsers(["firefox"], "https://example.ie")
    assert usable == [] and "doesn't trust the certificate" in why_not[0]
    assert firefox_profile.ENV not in browsers.os.environ  # not used when it doesn't help

    monkeypatch.setattr(browsers, "proxy_settings", lambda: None)  # no proxy: a certificate error is the site's
    answers = iter([""])
    assert browsers.usable_browsers(["firefox"], "https://example.ie") == (["firefox"], [])


def test_without_a_list_or_certutil_no_profile_is_made(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    for name in ("SSL_CERT_FILE", "NODE_EXTRA_CA_CERTS", "REQUESTS_CA_BUNDLE"):
        monkeypatch.delenv(name, raising=False)
    assert firefox_profile.build_profile() == ""
    bundle = tmp_path / "bundle.pem"
    bundle.write_text("-----BEGIN CERTIFICATE-----\nAAAA\n-----END CERTIFICATE-----\n")
    monkeypatch.setenv("SSL_CERT_FILE", str(bundle))
    monkeypatch.setattr(firefox_profile.shutil, "which", lambda name: None)
    assert firefox_profile.build_profile() == ""


class _Response:
    def __init__(self, kind: str, body: str) -> None:
        self.headers = {"content-type": kind}
        self._body = body

    def text(self) -> str:
        return self._body


def test_a_link_the_network_refuses_is_told_apart_from_the_sites_own_403() -> None:
    from site_audit.conftest import refused_by_this_network

    assert refused_by_this_network(_Response("text/plain; charset=utf-8",
                                              'request blocked: no rule or allowlist entry allows host "x.ie"'))
    assert not refused_by_this_network(_Response("text/html", "<h1>Forbidden</h1>"))
    assert not refused_by_this_network(_Response("text/plain", "Forbidden"))
