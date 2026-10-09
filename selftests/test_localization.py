"""Localization checks (ui_automation/localization.py) against real local sites in a real browser: a site in
English, Irish and German that does it right, and one with each common mistake (no lang, the wrong lang, a
template placeholder and a translation key showing, garbled characters, an "Irish" page still in English, a
German page that doesn't link back and is too wide for a phone, an Arabic page set left to right). Every
mistake must be found, and nothing on the good site."""

from __future__ import annotations

import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Iterator

import pytest
from playwright.sync_api import sync_playwright

from ui_automation import localization

EN = ("<p>Welcome to our shop. We make the best bread in the town and you can order it online for delivery to "
      "your door. Our bakers are in the shop from six in the morning, and we are open for you every day of the "
      "week with fresh bread, cakes and coffee.</p>")
GA = ("<p>Fáilte go dtí an siopa. Is é seo an t-arán is fearr sa bhaile agus is féidir leat é a ordú ar líne "
      "chun é a sheachadadh chuig do dhoras. Tá na báicéirí sa siopa ag a sé ar maidin agus tá muid ar oscailt "
      "gach lá den tseachtain le harán úr, cácaí agus caife. Is breá linn an obair seo agus tá fáilte romhat.</p>")
DE = ("<p>Willkommen in unserem Laden. Wir backen das beste Brot der Stadt und Sie können es online bestellen. "
      "Die Bäcker sind ab sechs Uhr im Laden und wir sind für Sie jeden Tag der Woche mit frischem Brot, Kuchen "
      "und Kaffee da. Das ist nicht nur ein Laden, es ist ein Ort für die ganze Familie und für Sie.</p>")


def _page(lang: str, body: str, alternates: str = "", dir_: str = "") -> str:
    lang_attr = f' lang="{lang}"' if lang else ""
    return (f"<!doctype html><html{lang_attr}{dir_}><head><meta charset='utf-8'>"
            f"<meta name='viewport' content='width=device-width,initial-scale=1'><title>Shop</title>{alternates}"
            f"</head><body><main>{body}</main></body></html>")


def _alternates(base: str, langs: list[tuple[str, str]]) -> str:
    return "".join(f'<link rel="alternate" hreflang="{code}" href="{base}{path}">' for code, path in langs)


SWITCHER = ('<nav><a href="/" hreflang="en">English</a> <a href="/ga/" hreflang="ga">Gaeilge</a> '
            '<a href="/de/" hreflang="de">Deutsch</a></nav>')
VERSIONS = [("en", "/"), ("ga", "/ga/"), ("de", "/de/"), ("x-default", "/")]


def good(base: str) -> dict[str, str]:
    alt = _alternates(base, VERSIONS)
    return {
        "/": _page("en-IE", "<h1>Bread</h1>" + SWITCHER + EN + '<a href="/about">About</a>', alt),
        "/about": _page("en-IE", "<h1>About</h1>" + EN),
        "/ga/": _page("ga", "<h1>Arán</h1>" + SWITCHER + GA, alt),
        "/de/": _page("de", "<h1>Brot</h1>" + SWITCHER + DE, alt),
    }


def bad(base: str) -> dict[str, str]:
    home_alt = _alternates(base, [("en", "/"), ("ga", "/ga/"), ("de", "/de/"), ("ar", "/ar/")])
    return {
        "/": _page("en", "<h1>Bread</h1>" + SWITCHER + EN + '<p>Total: {{ cart.total }}</p>'
                   "<button>checkout.button.submit</button><p>CafÃ© opening hours</p>", home_alt),
        "/about": _page("", "<h1>About</h1>" + EN),  # no lang
        "/menu": _page("en", "<h1>Speisekarte</h1>" + DE),  # says English, is German
        "/ga/": _page("ga", "<h1>Bread</h1>" + EN, home_alt),  # an "Irish" page still in English
        "/de/": _page("de", "<h1>Brot</h1>" + DE + '<div style="width:900px">Breit</div>'),  # no way back, too wide
        "/ar/": _page("ar", "<h1>خبز</h1><p>مرحبا</p>", home_alt),  # right-to-left language, left to right
    }


def _serve(make) -> Iterator[str]:  # noqa: ANN001
    pages: dict[str, str] = {}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            body = pages.get(self.path.split("?")[0])
            self.send_response(200 if body else 404)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write((body or _page("en", "<h1>Not found</h1>")).encode("utf-8"))

        def log_message(self, *args) -> None:  # noqa: ANN002
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    base = f"http://127.0.0.1:{server.server_port}"
    pages.update(make(base))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield base
    finally:
        server.shutdown()
        server.server_close()


def _audit(make, paths: list[str]) -> tuple[dict[str, localization.Finding], localization.Results]:  # noqa: ANN001
    for base in _serve(make):
        with sync_playwright() as p:
            browser = p.chromium.launch()
            try:
                context = browser.new_context()
                results = localization.audit(context.new_page(), context.request, [base + x for x in paths])
            finally:
                browser.close()
    return {f.check: f for f in results.findings}, results


def test_a_site_in_three_languages_done_right_passes() -> None:
    found, results = _audit(good, ["/", "/about"])
    assert set(found) == {"lang", "lang_matches", "leftovers", "garbled", "hreflang", "translated", "switcher",
                          "fits"}
    failed = {k: f.detail for k, f in found.items() if not f.passed}
    assert not failed, failed
    assert found["switcher"].detail == "Language links on the page: English, Gaeilge, Deutsch."
    pages = results.tables[0]["rows"]
    assert pages[0] == ["/", "en-IE", "English", "UTF-8", "4"]
    versions = {row[0]: row for row in results.tables[1]["rows"]}
    assert versions["ga"][3:] == ["ga", "Irish", "yes", "fits"] and versions["de"][4] == "German"


def test_each_common_mistake_is_found() -> None:
    found, _ = _audit(bad, ["/", "/about", "/menu"])
    assert found["lang"].detail == "no lang on <html>: /about"
    assert found["lang_matches"].detail == "/menu says en but its text is German"
    assert '"{{ cart.total }}" (template placeholder)' in found["leftovers"].detail
    assert '"checkout.button.submit" (translation key)' in found["leftovers"].detail
    assert found["garbled"].detail.startswith('/: "Ã©" in "CafÃ© opening hours"'), found["garbled"].detail
    hreflang = found["hreflang"].detail
    assert "de version doesn't link back to /" in hreflang
    assert found["translated"].detail == "/ga/ (ga) is still in English"
    assert found["fits"].detail.startswith("/de/ needs") and "at 375px" in found["fits"].detail
    assert not any(f.passed for k, f in found.items() if k not in ("switcher", "rtl"))


def test_a_right_to_left_page_must_say_so() -> None:
    def rtl(base: str) -> dict[str, str]:
        return {"/": _page("ar", "<h1>خبز</h1><p>مرحبا</p>"), "/he": _page("he", "<h1>לחם</h1>", dir_=' dir="rtl"')}

    found, _ = _audit(rtl, ["/", "/he"])
    assert not found["rtl"].passed and found["rtl"].detail == 'Not set to dir="rtl": / (ar)'


@pytest.mark.parametrize("text, expected", [(EN, "en"), (GA, "ga"), (DE, "de"), ("Buy now", "")])
def test_the_language_of_text_is_recognised_only_when_there_is_enough(text: str, expected: str) -> None:
    assert localization.language_of(text)[0] == expected


@pytest.mark.parametrize("text", ["Visit www.example.ie.", "Version 1.2.3", "e.g. this one", "Read the docs at "
                                  "docs.python.org.", "Contact hello@shop.ie"])
def test_ordinary_text_is_not_mistaken_for_a_leftover(text: str) -> None:
    assert localization.leftovers([text]) == []


def test_the_site_audit_runs_it_and_reports_what_it_found(tmp_path) -> None:  # noqa: ANN001
    from harness import base_config, invoke_cli

    for base in _serve(bad):
        cfg = base_config(base, artifacts={"video": "off"}, audit={"max_pages": 3, "check_external_links": False})
        run = invoke_cli(tmp_path / "run", ["site_audit", "-k", "crawl or language"], config=cfg)
    t = run.test("test_language_and_translations_are_right")
    assert t["outcome"] == "failed", run.output
    text = t["message"] + t["details"]
    assert "language or translation problem(s)" in t["message"]
    assert "No translation keys or placeholders showing: " in text and "(W3C Internationalization" in text
    assert "Each language version is really translated: /ga/ (ga) is still in English" in text
    assert [e["title"] for e in t["evidence"]][:2] == ["Language of 3 page(s)", "3 other language version(s)"]
