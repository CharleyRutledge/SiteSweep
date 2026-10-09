"""Reliability checks (ui_automation/reliability.py) against real local servers: up, an error page, nothing
answering, and a network that refuses the site (never counted as down). The MTBF / MTTR sums are checked by
hand-worked examples, and the private dashboard page (reliability/dashboard.html) must reach the same numbers
in a real browser."""

from __future__ import annotations

import json
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Iterator

import pytest
from playwright.sync_api import sync_playwright

from ui_automation import reliability

REPO = Path(__file__).resolve().parents[1]


@pytest.fixture
def site() -> Iterator[str]:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            self.send_response(500 if self.path == "/broken" else 200)
            self.end_headers()
            self.wfile.write(b"ok")

        def log_message(self, *args) -> None:  # noqa: ANN002
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()


@pytest.fixture
def refusing_proxy() -> Iterator[str]:
    """A proxy that refuses every site, as a cloud session's network does for sites it doesn't allow."""
    class Proxy(BaseHTTPRequestHandler):
        def do_CONNECT(self) -> None:  # noqa: N802
            self.send_response(403)
            self.end_headers()

        def log_message(self, *args) -> None:  # noqa: ANN002
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Proxy)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()


def _closed_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_up_error_and_nothing_answering(site: str, monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("HTTP_PROXY", "http_proxy", "HTTPS_PROXY", "https_proxy"):
        monkeypatch.delenv(name, raising=False)
    up, broken, gone = reliability.check([site + "/", site + "/broken", f"http://127.0.0.1:{_closed_port()}/"], 5)
    assert up["up"] is True and up["status"] == 200 and isinstance(up["ms"], int)
    assert broken["up"] is False and broken["status"] == 500 and broken["error"] == "HTTP 500"
    assert gone["up"] is False and gone["status"] is None and gone["error"]
    assert up["at"].endswith("Z") and len(up["at"]) == 20


def test_a_network_that_refuses_the_site_is_not_checked_never_down(refusing_proxy: str,
                                                                   monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HTTPS_PROXY", refusing_proxy)
    monkeypatch.delenv("NO_PROXY", raising=False)
    monkeypatch.delenv("no_proxy", raising=False)
    record = reliability.check_one("https://www.example.ie/", 5)
    assert record["up"] is None and record["error"].startswith("not checked"), record


def _hourly(url: str, pattern: str, start: int = 0) -> list[dict]:
    return [{"at": f"2026-10-01T{start + i:02d}:00:00Z", "url": url, "up": c == "u", "status": 200 if c == "u" else 503,
             "ms": 100 + i, "error": "" if c == "u" else "HTTP 503"} for i, c in enumerate(pattern)]


def test_mtbf_and_mttr_worked_by_hand() -> None:
    # 00 up, 01 up, 02 down, 03 down, 04 up, 05 up, 06 down, 07 up: two outages of 2 h and 1 h.
    records = _hourly("https://x.ie/", "uudduudu") + [{"at": "2026-10-01T08:00:00Z", "url": "https://x.ie/",
                                                       "up": None, "status": None, "ms": 5, "error": "not checked"}]
    s = reliability.stats(records, "https://x.ie/")
    assert s["checks"] == 8 and s["not_checked"] == 1
    assert s["uptime_pct"] == 62.5
    assert [(i["start"][11:13], i["end"][11:13], i["minutes"]) for i in s["incidents"]] == [("02", "04", 120),
                                                                                            ("06", "07", 60)]
    assert s["mttr_minutes"] == 90  # (120 + 60) / 2
    assert s["mtbf_hours"] == 2.0  # 7 h observed - 3 h down = 4 h up, over 2 outages
    assert s["down_now"] is False


def test_an_outage_still_going_and_a_site_never_down() -> None:
    s = reliability.stats(_hourly("https://x.ie/", "uuuudd"), "https://x.ie/")
    assert s["down_now"] is True and s["incidents"][0]["end"] is None and s["mttr_minutes"] is None
    assert s["mtbf_hours"] == 4.0  # up from 00 to 04; the open outage (04-05) is not counted as up
    calm = reliability.stats(_hourly("https://y.ie/", "uuuu"), "https://y.ie/")
    assert calm["uptime_pct"] == 100.0 and calm["incidents"] == [] and calm["mtbf_hours"] is None


def test_the_private_dashboard_does_the_same_sums(tmp_path: Path) -> None:
    records = _hourly("https://x.ie/", "uudduudu") + _hourly("https://y.ie/", "uuuudd", 3)
    page = tmp_path / "dashboard.html"
    page.write_text("<!doctype html><html><head><meta charset='utf-8'></head><body>"
                    + (REPO / "reliability" / "dashboard.html").read_text(encoding="utf-8") + "</body></html>",
                    encoding="utf-8")
    with sync_playwright() as p:
        browser = p.chromium.launch()
        pg = browser.new_page(viewport={"width": 375, "height": 800})
        pg.goto(page.as_uri())
        for url in ("https://x.ie/", "https://y.ie/"):
            assert pg.evaluate("([r, u]) => window.reliabilityStats(r, u)", [records, url]) == \
                reliability.stats(records, url)
        # With no store in a plain browser, the page says so instead of showing nothing.
        assert "can't be read" in pg.inner_text("#summary")
        assert pg.evaluate("document.documentElement.scrollWidth") <= 375
        browser.close()


def test_the_command_line(site: str, tmp_path: Path, capsys: pytest.CaptureFixture,
                          monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("HTTP_PROXY", "http_proxy"):
        monkeypatch.delenv(name, raising=False)
    assert reliability.main(["check", site + "/"]) == 0
    assert json.loads(capsys.readouterr().out)["up"] is True
    assert reliability.main(["check", "example.ie"]) == 2
    history = tmp_path / "history.jsonl"
    history.write_text("\n".join(json.dumps(r) for r in _hourly("https://x.ie/", "uudu")), encoding="utf-8")
    capsys.readouterr()
    assert reliability.main(["stats", str(history)]) == 0
    assert json.loads(capsys.readouterr().out)["mttr_minutes"] == 60


def test_an_mcp_server_is_up_only_when_it_completes_the_handshake(site: str, monkeypatch: pytest.MonkeyPatch) -> None:
    import mcp_servers

    for name in ("HTTP_PROXY", "http_proxy"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("NOTES_ADMIN_TOKEN", "admin-token")
    for url in mcp_servers.http_server(auth=True):
        up = reliability.check_mcp_one(url, 5, "NOTES_ADMIN_TOKEN")
        refused = reliability.check_mcp_one(url, 5)  # no login: the server refuses the handshake
    assert up["up"] is True and up["status"] == 200, up
    assert refused["up"] is False and refused["error"] == "HTTP 401: no handshake", refused
    page = reliability.check_mcp_one(site + "/", 5)  # a web page answers, but it is no MCP server
    assert page["up"] is False, page
