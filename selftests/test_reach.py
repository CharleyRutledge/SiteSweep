"""The cloud network check (python -m ui_automation.reach): against a stand-in for the session's proxy that
refuses some domains (HTTP 403, as Claude Code on the web does) and can't reach others (502)."""

from __future__ import annotations

import socketserver
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Iterator

import pytest

from ui_automation import reach

BLOCKED = {"blocked.example", "cdn.playwright.dev", "playwright.download.prss.microsoft.com"}


class _Proxy(socketserver.ThreadingTCPServer):
    daemon_threads = True
    allow_reuse_address = True


class _ConnectHandler(socketserver.StreamRequestHandler):
    def handle(self) -> None:
        line = self.rfile.readline().decode()
        while self.rfile.readline() not in (b"\r\n", b""):
            pass
        host = line.split()[1].rsplit(":", 1)[0] if line.startswith("CONNECT") else ""
        status = "403 Forbidden" if host in BLOCKED else "502 Bad Gateway"
        self.wfile.write(f"HTTP/1.1 {status}\r\nContent-Length: 0\r\nConnection: close\r\n\r\n".encode())


@pytest.fixture
def proxy(monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    server = _Proxy(("127.0.0.1", 0), _ConnectHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_address[1]}"
    for name in ("HTTPS_PROXY", "https_proxy"):
        monkeypatch.setenv(name, url)
    for name in ("NO_PROXY", "no_proxy"):
        monkeypatch.delenv(name, raising=False)
    yield url
    server.shutdown()
    server.server_close()


@pytest.fixture
def site() -> Iterator[str]:
    """A page that loads a script from a refused domain and an image from an unreachable one."""
    class Page(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            body = (b'<!doctype html><html lang="en"><title>Shop</title><h1>Shop</h1>'
                    b'<script src="https://blocked.example/app.js"></script>'
                    b'<img src="https://other.example/a.png" alt="">')
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args) -> None:  # noqa: ANN002
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Page)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}/"
    server.shutdown()
    server.server_close()


def _via(proxy: str) -> dict:
    """Browser settings for the stand-in proxy (the test page itself is on this computer, so it goes direct)."""
    return {"server": proxy, "bypass": "127.0.0.1"}


def test_a_refused_domain_is_told_apart_from_one_that_is_down(proxy) -> None:
    assert reach.is_blocked("blocked.example", timeout=5)
    assert not reach.is_blocked("other.example", timeout=5)  # unreachable, but not the session's rule


def test_domains_the_page_loads_from_are_found(proxy, site) -> None:
    assert reach.hosts_the_page_needs(site, proxy=_via(proxy)) == ["blocked.example", "other.example"]


def test_only_the_refused_domains_are_listed_with_the_browser_downloads(proxy, site, monkeypatch) -> None:
    real = reach.hosts_the_page_needs
    monkeypatch.setattr(reach, "hosts_the_page_needs", lambda url: real(url, proxy=_via(proxy)))
    monkeypatch.setattr(reach, "missing_browsers", lambda names: [])
    assert reach.domains_to_allow(site) == ["blocked.example"]
    monkeypatch.setattr(reach, "missing_browsers", lambda names: ["firefox"])
    assert reach.domains_to_allow(site) == ["blocked.example", "cdn.playwright.dev",
                                            "playwright.download.prss.microsoft.com"]


def test_a_refused_site_is_listed_first(proxy, monkeypatch) -> None:
    monkeypatch.setattr(reach, "missing_browsers", lambda names: [])
    monkeypatch.setenv("CLAUDE_CODE_REMOTE", "true")
    code, message = reach.report("https://blocked.example/shop")
    assert code == 4
    assert "allow these domains:\n\n    blocked.example\n\nHow:" in message and "Custom" in message


def test_an_address_on_your_computer_points_to_the_desktop_app_or_remote_control(monkeypatch) -> None:
    monkeypatch.setenv("CLAUDE_CODE_REMOTE", "true")
    code, message = reach.report("http://localhost:8082")
    assert code == 3 and "Claude Desktop app" in message and "claude remote-control" in message
    monkeypatch.delenv("CLAUDE_CODE_REMOTE")
    assert reach.report("http://localhost:8082")[0] == 0  # on your own computer there is nothing to set up


def test_a_bad_address_is_refused(capsys) -> None:
    assert reach.main(["example.ie"]) == 2
    assert "http:// or https://" in capsys.readouterr().err
