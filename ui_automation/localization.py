"""Localization checks: each page says which language it is in, and says it correctly; no translation keys or
placeholders left showing; no garbled characters; right-to-left languages set to read right to left; and, for a
site in several languages, every language version is linked correctly (hreflang), opens, is really translated,
links back, fits a phone screen, and can be reached from a language switcher.

The language of a page's text is recognised from its most common short words (the, and, agus, und, le...): enough
to tell an English page from an Irish or German one, never a judgement of the translation's quality.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

LANG_TAG = re.compile(r"^[a-zA-Z]{2,3}(-[a-zA-Z0-9]{2,8})*$")
RTL = {"ar", "he", "fa", "ur", "ps", "yi", "dv", "ug", "ku", "sd"}
# The most common short words of each language: a page's language is the one most of its words come from.
COMMON_WORDS = {
    "en": "the and of to in is for that with you are this on your our we be it as or at by from".split(),
    "ga": "agus an na ar is le do go ag sa ar níl atá bhí seo sin mar ach chun faoi".split(),
    "fr": "le la les et des du un une est pour que dans en sur pas vous nous avec sont au".split(),
    "de": "der die das und ist nicht ein eine zu den von mit sich auf für dem sie wir ihr".split(),
    "es": "el la los las y de que en un una es por para con no su se del al como".split(),
    "it": "il la di e che è un una per non in con sono del della le gli al si".split(),
    "nl": "de het een en van is dat op te in voor niet met zijn je wij u aan er".split(),
    "pt": "o a os as e de que em um uma é para com não do da no na por se".split(),
    "pl": "i w na z nie się do to jest że o jak po co za od tak ale".split(),
}
NAMES = {"en": "English", "ga": "Irish", "fr": "French", "de": "German", "es": "Spanish", "it": "Italian",
         "nl": "Dutch", "pt": "Portuguese", "pl": "Polish"}
SWITCHER_WORDS = re.compile(r"^\s*(English|Gaeilge|Irish|Français|Deutsch|Español|Italiano|Nederlands|Português|"
                            r"Polski|EN|GA|FR|DE|ES|IT|NL|PT|PL|Language|Languages|Teanga)\s*$", re.I)
# Text that was meant to be replaced by a translation.
LEFTOVERS = [
    (re.compile(r"\{\{\s*[\w.$-]+\s*\}\}"), "template placeholder"),
    (re.compile(r"\$\{[\w.]+\}"), "template placeholder"),
    (re.compile(r"\[\[\s*[\w.-]+\s*\]\]"), "translation placeholder"),
    (re.compile(r"(?i)translation missing|missing translation|MISSING_TRANSLATION|\[missing \""), "missing translation"),
    (re.compile(r"[a-z][a-zA-Z0-9_]*(?:\.[a-z][a-zA-Z0-9_]*){2,}"), "translation key"),
    (re.compile(r"__[A-Z][A-Z0-9_]+__"), "placeholder"),
]
GARBLED = re.compile(r"Ã[\u0080-¿]|â€[\u0080-¿‘-”™]|�")
URLISH = re.compile(r"(?i)(https?://|www\.|@|\.(com|ie|eu|org|net|js|css|png|jpg|svg|pdf)\b)")

PAGE_JS = """() => {
    const walker = document.createTreeWalker(document.body || document.documentElement, NodeFilter.SHOW_TEXT, {
        acceptNode: n => {
            const p = n.parentElement;
            if (!p || ['SCRIPT', 'STYLE', 'NOSCRIPT', 'CODE', 'PRE', 'TEMPLATE'].includes(p.tagName)) return 2;
            const s = getComputedStyle(p);
            return (s.display === 'none' || s.visibility === 'hidden') ? 2 : 1;
        }});
    const texts = [];
    while (walker.nextNode()) { const t = walker.currentNode.textContent.trim(); if (t) texts.push(t.slice(0, 300)); }
    const attrs = [...document.querySelectorAll('[placeholder], [title], [aria-label], img[alt], input[type=submit][value]')]
        .flatMap(e => ['placeholder', 'title', 'aria-label', 'alt', 'value'].map(a => e.getAttribute(a)).filter(Boolean));
    return {
        lang: document.documentElement.getAttribute('lang') || '',
        dir: document.documentElement.getAttribute('dir') || getComputedStyle(document.documentElement).direction,
        charset: document.characterSet,
        hreflang: [...document.querySelectorAll('link[rel~=alternate][hreflang]')]
            .map(l => ({lang: l.getAttribute('hreflang'), href: l.href})),
        links: [...document.querySelectorAll('a[href]')].map(a => ({text: (a.innerText || '').trim().slice(0, 40),
            hreflang: a.getAttribute('hreflang') || a.getAttribute('lang') || '', href: a.href})),
        texts, attrs,
        overflow: document.documentElement.scrollWidth - document.documentElement.clientWidth,
    };
}"""


def language_of(text: str) -> tuple[str, int]:
    """The language most of the text's common words come from, and how many of them were found ('' when there
    are too few words to tell)."""
    words = re.findall(r"[^\W\d_]+", text.lower())
    counts = {lang: sum(1 for w in words if w in set(common)) for lang, common in COMMON_WORDS.items()}
    best = max(counts, key=counts.get)
    ranked = sorted(counts.values(), reverse=True)
    if ranked[0] < 8 or ranked[0] < 1.5 * ranked[1]:
        return "", ranked[0]
    return best, ranked[0]


def leftovers(texts: list[str]) -> list[tuple[str, str]]:
    """(what, text) for each placeholder or translation key left showing."""
    found = []
    for t in texts:
        for pattern, what in LEFTOVERS:
            # A key only counts when it is all the text there is (a button or heading that shows "home.hero.title").
            m = pattern.fullmatch(t.strip()) if what == "translation key" else pattern.search(t)
            if m and not (what == "translation key" and URLISH.search(t)):
                found.append((what, m.group(0)))
                break
    return found


@dataclass
class Finding:
    check: str
    passed: bool
    detail: str
    title: str = ""
    law: str = ""  # the guideline it relates to (named "law" like the other checks, for the report)


@dataclass
class Results:
    findings: list[Finding] = field(default_factory=list)
    tables: list[dict] = field(default_factory=list)


TITLES = {
    "lang": "Each page says which language it is in",
    "lang_matches": "The language it says is the language it's in",
    "leftovers": "No translation keys or placeholders showing",
    "garbled": "No garbled characters",
    "rtl": "Right-to-left languages read right to left",
    "hreflang": "Language versions linked correctly (hreflang)",
    "translated": "Each language version is really translated",
    "switcher": "Visitors can switch language",
    "fits": "Translated pages fit a phone screen",
}
GUIDES = {
    "lang": "WCAG 2.1 SC 3.1.1 Language of Page",
    "lang_matches": "WCAG 2.1 SC 3.1.1 (screen readers read the page in the language it says)",
    "leftovers": "W3C Internationalization best practice",
    "garbled": "W3C: declare and use UTF-8",
    "rtl": "W3C: structural markup and right-to-left text in HTML",
    "hreflang": "Google Search hreflang rules (codes valid, each version lists itself and links back)",
    "translated": "W3C Internationalization best practice",
    "switcher": "W3C: language negotiation and switchers",
    "fits": "WCAG 2.1 SC 1.4.10 Reflow (translations are often longer)",
}


def _short(url: str) -> str:
    p = urlparse(url)
    return (p.path or "/") + (f"?{p.query}" if p.query else "")


def _add(out: Results, check: str, passed: bool, detail: str) -> None:
    out.findings.append(Finding(check, passed, detail, TITLES[check], GUIDES[check]))


def audit(page: Any, request: Any, pages: list[str], max_versions: int = 6) -> Results:
    """Every check on `pages` (opened in `page`), then on each language version the home page links to."""
    out = Results()
    seen: dict[str, dict] = {}
    rows = []
    for url in pages:
        info = _open(page, url)
        if info is None:
            continue
        seen[url] = info
        detected, count = language_of(" ".join(info["texts"]))
        rows.append([_short(url), info["lang"] or "not set", NAMES.get(detected, detected) or "too little text",
                     info["charset"], str(len(info["hreflang"]))])
    if not seen:
        return out

    no_lang = [_short(u) for u, i in seen.items() if not i["lang"]]
    bad_lang = [f"{_short(u)} ({i['lang']})" for u, i in seen.items() if i["lang"] and not LANG_TAG.match(i["lang"])]
    _add(out, "lang", not no_lang and not bad_lang,
         f"All {len(seen)} page(s) set a valid lang on <html>." if not (no_lang or bad_lang) else
         "; ".join(filter(None, [f"no lang on <html>: {', '.join(no_lang)}" if no_lang else "",
                                 f"not a valid language code: {', '.join(bad_lang)}" if bad_lang else ""])))

    wrong = []
    for u, i in seen.items():
        detected, _ = language_of(" ".join(i["texts"]))
        said = i["lang"].split("-")[0].lower()
        if detected and said and said in COMMON_WORDS and detected != said:
            wrong.append(f"{_short(u)} says {i['lang']} but its text is {NAMES[detected]}")
    _add(out, "lang_matches", not wrong, "; ".join(wrong) if wrong else
         "Where there was enough text to tell, every page is in the language it says.")

    left = [f"{_short(u)}: \"{text}\" ({what})" for u, i in seen.items() for what, text in leftovers(i["texts"] + i["attrs"])]
    _add(out, "leftovers", not left, "; ".join(left[:10]) if left else "No placeholders or translation keys showing.")

    garbled = [f"{_short(u)}: \"{m.group(0)}\" in \"{t[:60]}\"" for u, i in seen.items() for t in i["texts"]
               if (m := GARBLED.search(t))]
    _add(out, "garbled", not garbled, "; ".join(garbled[:6]) + (" (usually text saved in one encoding and shown in "
                                                                 "another: use UTF-8 throughout)" if garbled else "")
         if garbled else "No garbled characters (mojibake) in the text.")

    rtl = [f"{_short(u)} ({i['lang']})" for u, i in seen.items()
           if i["lang"].split("-")[0].lower() in RTL and i["dir"] != "rtl"]
    if any(i["lang"].split("-")[0].lower() in RTL for i in seen.values()):
        _add(out, "rtl", not rtl, f"Not set to dir=\"rtl\": {', '.join(rtl)}" if rtl else
             "Right-to-left pages are set to dir=\"rtl\".")

    out.tables.append({"title": f"Language of {len(seen)} page(s)",
                       "columns": ["Page", "Says (lang)", "Text looks like", "Characters", "Language versions listed"],
                       "rows": rows, "note": "The text's language is recognised from its most common short words."})

    home, info = next(iter(seen.items()))
    _versions(out, page, request, home, info, max_versions)
    return out


def _open(page: Any, url: str) -> dict | None:
    try:
        page.goto(url, wait_until="load", timeout=30_000)
        page.wait_for_timeout(300)
        return page.evaluate(PAGE_JS)
    except Exception:  # noqa: BLE001 - a page that won't open is reported by the page checks
        return None


def _versions(out: Results, page: Any, request: Any, home: str, info: dict, max_versions: int) -> None:
    alternates = [a for a in info["hreflang"] if a["href"]]
    switch_links = [l for l in info["links"] if l["hreflang"] or SWITCHER_WORDS.match(l["text"])]
    if not alternates:
        if switch_links:
            _add(out, "hreflang", False, "The page links to other languages but doesn't list them with "
                                         "<link rel=\"alternate\" hreflang>, so search engines can't match them up.")
        return  # a site in one language: nothing more to check
    problems = []
    codes = [a["lang"] for a in alternates]
    bad = [c for c in codes if c != "x-default" and not LANG_TAG.match(c)]
    if bad:
        problems.append(f"not valid language codes: {', '.join(bad)}")
    if not any(a["href"].rstrip("/") == home.rstrip("/") for a in alternates):
        problems.append("the page doesn't list itself among its language versions")
    version_rows, untranslated, too_wide = [], [], []
    home_lang = info["lang"].split("-")[0].lower()
    for alt in alternates[:max_versions]:
        if alt["href"].rstrip("/") == home.rstrip("/") or alt["lang"] == "x-default":
            continue
        status = ""
        try:
            status = str(request.get(alt["href"], fail_on_status_code=False, timeout=15_000).status)
        except Exception:  # noqa: BLE001
            status = "no answer"
        other = _open(page, alt["href"]) if status.isdigit() and int(status) < 400 else None
        if other is None:
            problems.append(f"{alt['lang']} version {_short(alt['href'])} doesn't open (HTTP {status})")
            version_rows.append([alt["lang"], _short(alt["href"]), status, "", "", "", ""])
            continue
        links_back = any(a["href"].rstrip("/") == home.rstrip("/") for a in other["hreflang"])
        if not links_back:
            problems.append(f"{alt['lang']} version doesn't link back to {_short(home)}")
        detected, _ = language_of(" ".join(other["texts"]))
        want = alt["lang"].split("-")[0].lower()
        if want != home_lang and detected and detected == home_lang:
            untranslated.append(f"{_short(alt['href'])} ({alt['lang']}) is still in {NAMES[detected]}")
        if other["lang"] and other["lang"].split("-")[0].lower() != want:
            problems.append(f"{alt['lang']} version says lang=\"{other['lang']}\"")
        wide = _width_at_phone(page, alt["href"])
        if wide > 0:
            too_wide.append(f"{_short(alt['href'])} needs {wide}px sideways scrolling at 375px")
        version_rows.append([alt["lang"], _short(alt["href"]), status, other["lang"] or "not set",
                             NAMES.get(detected, detected) or "too little text", "yes" if links_back else "no",
                             f"{wide}px too wide" if wide > 0 else "fits"])
    _add(out, "hreflang", not problems, "; ".join(problems) if problems else
         f"{len(alternates)} language version(s) listed; each opens and links back.")
    _add(out, "translated", not untranslated, "; ".join(untranslated) if untranslated else
         "Each language version's text is in its own language (where there was enough text to tell).")
    _add(out, "switcher", bool(switch_links), f"Language links on the page: "
         f"{', '.join(l['text'] or l['hreflang'] for l in switch_links[:6])}." if switch_links else
         "There are language versions, but no visible link to them on the page.")
    _add(out, "fits", not too_wide, "; ".join(too_wide) if too_wide else
         "Every language version fits a 375px phone screen.")
    out.tables.append({"title": f"{len(version_rows)} other language version(s)",
                       "columns": ["Language", "Page", "HTTP", "Says (lang)", "Text looks like", "Links back?",
                                   "At 375px"], "rows": version_rows, "note": ""})


def _width_at_phone(page: Any, url: str) -> int:
    size = page.viewport_size
    try:
        page.set_viewport_size({"width": 375, "height": 800})
        page.goto(url, wait_until="load", timeout=30_000)
        return int(page.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth"))
    except Exception:  # noqa: BLE001
        return 0
    finally:
        if size:
            page.set_viewport_size(size)
