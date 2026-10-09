"""GDPR and cookie checks, done the way the EDPB's website auditing tool does them: the site is visited three
times in fresh browsers (no choice made, after "Reject", after "Accept"), and every cookie, browser storage item
and third-party request is recorded each time. Then the cookie banner, the privacy notice and the forms that
collect personal data are checked.

Read-only: the only clicks are on the cookie banner's own buttons, forms are never submitted, and requests to
known trackers are recorded and blocked, so a test never sends analytics. These checks find clear problems; they
cannot prove a site complies with GDPR. That needs a person, and legal advice for the wording.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

from ui_automation.compliance import TRACKER_HOSTS, TRACKING_COOKIE, CheckResult, _find_link, _links
from ui_automation.local import is_local

LAW = {
    "no_tracking_before_consent": "ePrivacy Regulations 2011 (S.I. 336/2011) Reg. 5(3); GDPR Art. 6 and 7",
    "reject_as_easy": "DPC guidance on cookies (2020); EDPB cookie banner taskforce report (2023)",
    "no_pre_ticked": "GDPR Art. 4(11) and 7; CJEU Planet49 (C-673/17)",
    "reject_works": "ePrivacy Regulations 2011 Reg. 5(3); GDPR Art. 7",
    "change_your_mind": "GDPR Art. 7(3): withdrawing consent must be as easy as giving it",
    "outside_eu_before_consent": "GDPR Chapter V (Art. 44-49), and consent first (ePrivacy Reg. 5(3))",
    "privacy_notice_content": "GDPR Art. 13 and 14",
    "forms": "GDPR Art. 13 (inform when collecting) and Art. 32 (security)",
}
TITLES = {
    "no_tracking_before_consent": "No tracking before you choose",
    "reject_as_easy": "Rejecting is as easy as accepting",
    "no_pre_ticked": "No pre-ticked boxes",
    "reject_works": "\"Reject\" really stops tracking",
    "change_your_mind": "You can change your mind later",
    "outside_eu_before_consent": "No data sent outside the EU before you choose",
    "privacy_notice_content": "Privacy notice says what GDPR requires",
    "forms": "Forms that collect personal data are safe and explained",
}

# Who is behind common third-party addresses, and where the company is based.
COMPANIES = {
    "google-analytics.com": ("Google", "USA"), "googletagmanager.com": ("Google", "USA"),
    "doubleclick.net": ("Google", "USA"), "googleadservices.com": ("Google", "USA"),
    "googlesyndication.com": ("Google", "USA"), "google.com": ("Google", "USA"), "gstatic.com": ("Google", "USA"),
    "googleapis.com": ("Google", "USA"), "youtube.com": ("Google (YouTube)", "USA"),
    "facebook.com": ("Meta", "USA"), "facebook.net": ("Meta", "USA"), "instagram.com": ("Meta", "USA"),
    "clarity.ms": ("Microsoft", "USA"), "bing.com": ("Microsoft", "USA"),
    "linkedin.com": ("LinkedIn (Microsoft)", "USA"), "licdn.com": ("LinkedIn (Microsoft)", "USA"),
    "hotjar.com": ("Hotjar", "Malta (EU)"), "tiktok.com": ("TikTok", "outside the EU"),
    "twitter.com": ("X (Twitter)", "USA"), "ads-twitter.com": ("X (Twitter)", "USA"), "x.com": ("X (Twitter)", "USA"),
    "pinterest.com": ("Pinterest", "USA"), "hubspot.com": ("HubSpot", "USA"), "hs-scripts.com": ("HubSpot", "USA"),
    "hs-analytics.net": ("HubSpot", "USA"), "intercom.io": ("Intercom", "USA"), "cloudflare.com": ("Cloudflare", "USA"),
    "vimeo.com": ("Vimeo", "USA"), "stripe.com": ("Stripe", "USA (EU entity in Ireland)"),
}
# Cookies that remember the visitor's cookie choice itself: strictly necessary, fine before consent.
CONSENT_COOKIE = re.compile(r"^(cmplz_|CookieConsent|OptanonConsent|OptanonAlertBoxClosed|cookieyes-consent|"
                            r"euconsent|borlabs-cookie|cookie_?consent|cookielawinfo|moove_gdpr|catAccCookies)", re.I)
TRACKING_STORAGE = re.compile(r"^(_hj|amplitude|mixpanel|ajs_|_ga|__anon_id|_fbp|intercom|hubspot)", re.I)

ACCEPT = re.compile(r"^\s*(accept( all| cookies)?|agree|i agree|allow( all)?( cookies)?|ok|got it|yes)\s*$", re.I)
REJECT = re.compile(r"^\s*(reject( all| cookies)?|decline( all)?|deny( all)?|refuse( all)?|no,? thanks|"
                    r"(only |accept only )?(necessary|essential)( cookies)?( only)?|continue without accepting)\s*$", re.I)
SETTINGS = re.compile(r"(cookie|privacy|consent) (settings|preferences|choices)|manage (cookies|consent|choices)|"
                      r"change (consent|cookie)|view preferences|customi[sz]e", re.I)

# What GDPR Art. 13 says a privacy notice must tell people, and words that show the notice covers it.
NOTICE_ITEMS = [
    ("Who is responsible (the controller) and how to contact them", r"controller|who we are|contact us|data protection officer"),
    ("Contact details of the data protection officer, if there is one", r"data protection officer|\bDPO\b"),
    ("Why personal data is used (the purposes)", r"purpose|we use (your|personal) (data|information)|why we"),
    ("The legal basis for each use", r"legal basis|lawful basis|legitimate interest|performance of a contract|your consent"),
    ("Who the data is shared with", r"recipient|third part|share|processor|service provider"),
    ("Transfers outside the EU and how they are protected", r"outside (the )?(EU|EEA|European)|international transfer|standard contractual|adequacy"),
    ("How long the data is kept", r"retain|retention|how long|kept for|period"),
    ("People's rights (access, correction, deletion, objection, portability)", r"right (of|to) (access|erasure|rectification|object|portability)|access your|delete your|erasure"),
    ("That consent can be withdrawn at any time", r"withdraw"),
    ("The right to complain to the Data Protection Commission", r"Data Protection Commission|supervisory authority|dataprotection\.ie|lodge a complaint"),
]

PERSONAL_FIELDS_JS = """() => [...document.forms].map(f => {
    const fields = [...f.querySelectorAll('input, textarea, select')].filter(i => {
        const t = (i.type || '').toLowerCase(), n = ((i.name || '') + ' ' + (i.id || '') + ' ' + (i.autocomplete || '')
            + ' ' + (i.placeholder || '')).toLowerCase();
        if (['hidden', 'submit', 'button', 'checkbox', 'radio', 'search'].includes(t)) return false;
        return ['email', 'tel'].includes(t) || /e-?mail|phone|mobile|name|address|birth|dob|iban|card/.test(n);
    }).map(i => (i.name || i.id || i.type || 'field'));
    const ticked = [...f.querySelectorAll('input[type=checkbox]')].filter(c => c.checked && !c.disabled
        && /newsletter|marketing|offers|news|updates|promot|partners/i.test((c.closest('label') || c.parentElement || c).innerText + ' ' + (c.name || '')))
        .map(c => ((c.closest('label') || c.parentElement || c).innerText || c.name || 'checkbox').trim().slice(0, 60));
    return {fields, action: f.action || location.href, ticked};
}).filter(f => f.fields.length)"""

BANNER_JS = """el => {
    const box = el.closest('[role=dialog],[aria-modal=true],[id*=cookie i],[class*=cookie i],[id*=consent i],'
        + '[class*=consent i],[id*=cmp i],[class*=cmp i],[id*=gdpr i],[class*=gdpr i]') || el.parentElement;
    return [...box.querySelectorAll('input[type=checkbox]')].filter(c => c.checked && !c.disabled)
        .map(c => ((c.closest('label') || c.parentElement || c).innerText || c.name || 'checkbox').trim().slice(0, 60));
}"""


FORM_PAGES = re.compile(r"contact|sign-?up|register|join|subscribe|newsletter|enquir|quote|book|checkout|account|apply",
                        re.I)
NOTICE_PAGES = re.compile(r"privacy|data-protection|gdpr|cookie", re.I)


def pick_pages(urls: list[str], count: int) -> list[str]:
    """The pages to visit: the home page first, then pages that usually ask for personal data (contact, sign-up,
    checkout...), then the rest in crawl order. The privacy notice is read separately, so it is left out."""
    home, rest = urls[:1], [u for u in urls[1:] if not NOTICE_PAGES.search(urlparse(u).path)]
    forms = [u for u in rest if FORM_PAGES.search(urlparse(u).path)]
    return (home + forms + [u for u in rest if u not in forms])[:count]


def company(host: str) -> tuple[str, str]:
    for suffix, who in COMPANIES.items():
        if host == suffix or host.endswith("." + suffix):
            return who
    return ("", "")


def _is_tracker(url: str) -> bool:
    return any(h in url for h in TRACKER_HOSTS)


@dataclass
class Visit:
    """What one browser (one consent choice) stored and contacted across the pages it opened."""
    cookies: list[dict] = field(default_factory=list)
    storage: dict[str, list[str]] = field(default_factory=dict)  # origin -> keys
    third_party: dict[str, int] = field(default_factory=dict)  # host -> requests
    trackers: list[str] = field(default_factory=list)  # tracker request addresses (blocked)
    clicked: str = ""  # the banner button pressed, if any
    page: Any = None  # the last page, still open, when visit(keep_open=True)

    def non_essential(self, site_host: str) -> list[str]:
        """What needs consent: tracking cookies, other sites' cookies, tracking storage, tracker requests."""
        found = [f"cookie {c['name']} ({c['domain'].lstrip('.')})" for c in self.cookies
                 if not CONSENT_COOKIE.match(c["name"])
                 and (TRACKING_COOKIE.match(c["name"]) or not _same_site(c["domain"], site_host))]
        found += [f"stored item {k} ({o})" for o, keys in self.storage.items() for k in keys if TRACKING_STORAGE.match(k)]
        found += [f"request to {h}" for h in sorted({urlparse(u).hostname or u for u in self.trackers})]
        return found


def _site(host: str) -> str:
    """The registrable part of a host name: www.shop.example.ie -> example.ie, a.example.co.uk -> example.co.uk.
    An IP address or a one-word name (localhost) stands for itself."""
    host = host.lower().strip(".")
    parts = host.split(".")
    if len(parts) < 2 or host.replace(".", "").isdigit():
        return host
    keep = 3 if len(parts) >= 3 and len(parts[-1]) == 2 and parts[-2] in ("co", "com", "org", "net", "gov", "ac", "edu") else 2
    return ".".join(parts[-keep:])


def _same_site(domain: str, site_host: str) -> bool:
    return _site(domain) == _site(site_host)


def _outside_eu(where: str) -> bool:
    return bool(where) and "(EU" not in where and "EU entity" not in where


def _buttons(page: Any, pattern: re.Pattern) -> Any:
    """The first visible button (or button-like link) whose text matches, or None."""
    for role in ("button", "link"):
        loc = page.get_by_role(role, name=pattern)
        for i in range(min(loc.count(), 10)):
            item = loc.nth(i)
            try:
                if item.is_visible() and (role == "button" or (item.get_attribute("href") or "#").startswith(("#", "javascript"))):
                    return item
            except Exception:  # noqa: BLE001 - element went away while looking
                continue
    return None


def visit(context: Any, urls: list[str], choice: str = "", settle_ms: int = 1500, keep_open: bool = False) -> Visit:
    """Open `urls` in `context`, after pressing the banner's Accept or Reject on the first page when `choice` says so."""
    result = Visit()
    site_host = urlparse(urls[0]).hostname or ""

    def on_request(request: Any) -> None:
        host = urlparse(request.url).hostname or ""
        if host and not _same_site(host, site_host) and request.url.startswith("http"):
            result.third_party[host] = result.third_party.get(host, 0) + 1

    def block(route: Any) -> None:
        result.trackers.append(route.request.url)
        route.abort()

    context.on("request", on_request)
    context.route(lambda url: _is_tracker(url), block)
    page = context.new_page()
    for i, url in enumerate(urls):
        try:
            page.goto(url, wait_until="load", timeout=30_000)
            page.wait_for_timeout(settle_ms)
        except Exception:  # noqa: BLE001 - a page that won't load is the other checks' business
            continue
        if i == 0 and choice:
            button = _buttons(page, ACCEPT if choice == "accept" else REJECT)
            if button is not None:
                result.clicked = (button.inner_text() or "").strip()[:40]
                try:
                    button.click(timeout=5_000)
                    page.wait_for_timeout(settle_ms)
                except Exception:  # noqa: BLE001
                    result.clicked = ""
        try:
            keys = page.evaluate("() => { try { return Object.keys(localStorage); } catch (e) { return []; } }")
            result.storage[urlparse(page.url).netloc] = sorted(set(keys) | set(result.storage.get(urlparse(page.url).netloc, [])))
        except Exception:  # noqa: BLE001
            pass
    result.cookies = context.cookies()
    if keep_open:
        result.page = page
    else:
        page.close()
    return result


def banner(page: Any) -> dict:
    """The cookie banner as a visitor first sees it: its buttons, their sizes, and ticked boxes."""
    accept, reject, settings = _buttons(page, ACCEPT), _buttons(page, REJECT), _buttons(page, SETTINGS)

    def area(loc: Any) -> int:
        box = loc.bounding_box() if loc is not None else None
        return int(box["width"] * box["height"]) if box else 0

    def text(loc: Any) -> str:
        return (loc.inner_text() or "").strip()[:40] if loc is not None else ""

    ticked = accept.evaluate(BANNER_JS) if accept is not None else []
    return {"accept": text(accept), "reject": text(reject), "settings": text(settings),
            "accept_area": area(accept), "reject_area": area(reject), "ticked": ticked}


def notice_items(text: str) -> list[tuple[str, bool, str]]:
    """Each Art. 13 item: whether the notice mentions it, and the words that showed it."""
    out = []
    for item, pattern in NOTICE_ITEMS:
        m = re.search(pattern, text, re.I)
        out.append((item, bool(m), m.group(0) if m else ""))
    return out


@dataclass
class Findings:
    results: list[CheckResult]
    tables: list[dict]  # evidence tables for the report


def _result(check: str, ok: bool, detail: str) -> CheckResult:
    return CheckResult(check, ok, detail, law=LAW[check], title=TITLES[check])


def _days(expires: float) -> str:
    if not expires or expires < 0:
        return "until the browser closes"
    days = (expires - time.time()) / 86400
    return f"{days:.0f} day(s)" if days >= 1 else "under a day"


def audit(browser: Any, urls: list[str], context_args: dict | None = None) -> Findings:
    """The GDPR and cookie checks on `urls` (the home page first)."""
    args = context_args or {}
    site_host = urlparse(urls[0]).hostname or ""
    local = is_local(urls[0])
    results: list[CheckResult] = []

    ctx = browser.new_context(**args)
    before = visit(ctx, urls)
    first = ctx.new_page()
    first.goto(urls[0], wait_until="load", timeout=30_000)
    first.wait_for_timeout(1500)
    shown = banner(first)
    links = _links(first)
    notice_link = _find_link(links, r"privacy|data protection|gdpr")
    notice_text = ""
    if notice_link:
        try:
            first.goto(notice_link["href"], wait_until="load", timeout=30_000)
            notice_text = first.inner_text("body")
        except Exception:  # noqa: BLE001
            notice_text = ""
    forms = []
    for url in urls:
        try:
            first.goto(url, wait_until="load", timeout=30_000)
            has_notice = bool(_find_link(_links(first), r"privacy|data protection|gdpr"))
            # An app on this computer has no HTTPS: that is checked on the deployed site (as "Served securely").
            forms += [{**f, "page": url, "notice": has_notice,
                       "https": local or (first.url.startswith("https://") and f["action"].startswith("https://"))}
                      for f in first.evaluate(PERSONAL_FIELDS_JS)]
        except Exception:  # noqa: BLE001
            continue
    ctx.close()

    ctx = browser.new_context(**args)
    rejected = visit(ctx, urls, "reject", keep_open=True)
    change_text = ""
    if rejected.clicked:  # after choosing, the home page must still offer a way to change the choice
        try:
            rejected.page.goto(urls[0], wait_until="load", timeout=30_000)
            rejected.page.wait_for_timeout(1500)
            change = _buttons(rejected.page, SETTINGS)
            change_text = (change.inner_text() or "").strip()[:40] if change is not None else ""
        except Exception:  # noqa: BLE001
            change_text = ""
    ctx.close()

    ctx = browser.new_context(**args)
    accepted = visit(ctx, urls, "accept")
    ctx.close()

    early = before.non_essential(site_host)
    results.append(_result("no_tracking_before_consent", not early,
                           "Nothing that tracks people loads before a choice is made." if not early else
                           f"Before any choice: {'; '.join(early[:8])}."))

    has_banner = bool(shown["accept"] or shown["reject"])
    if not has_banner:
        reject_detail = ("No cookie banner found. That is fine only if the site sets nothing that needs consent "
                         "(see the first check).")
        reject_ok = not early
    elif not shown["reject"]:
        reject_detail = f"The banner offers \"{shown['accept']}\" but no reject button on the same screen."
        reject_ok = False
    elif shown["accept_area"] and shown["reject_area"] < 0.5 * shown["accept_area"]:
        reject_detail = (f"\"{shown['reject']}\" is much smaller than \"{shown['accept']}\" "
                         f"({shown['reject_area']} vs {shown['accept_area']} px²): rejecting is made harder.")
        reject_ok = False
    else:
        reject_detail = f"\"{shown['reject']}\" is on the first screen, as easy as \"{shown['accept']}\"."
        reject_ok = True
    results.append(_result("reject_as_easy", reject_ok, reject_detail))

    results.append(_result("no_pre_ticked", not shown["ticked"],
                           "No boxes ticked in advance in the banner." if not shown["ticked"] else
                           f"Ticked in advance: {', '.join(shown['ticked'])}."))

    if rejected.clicked:
        after = rejected.non_essential(site_host)
        results.append(_result("reject_works", not after,
                               f"After \"{rejected.clicked}\", nothing that tracks people loads." if not after else
                               f"After \"{rejected.clicked}\": {'; '.join(after[:8])}."))
        results.append(_result("change_your_mind", bool(change_text),
                               f"\"{change_text}\" stays available after choosing."
                               if change_text else "After choosing, nothing on the page lets people change "
                                                          "their choice (e.g. a 'Cookie settings' link)."))

    tracked = {urlparse(u).hostname for u in before.trackers}
    abroad = sorted({f"{company(h)[0]} ({company(h)[1]})" for h in before.third_party
                     if _outside_eu(company(h)[1]) and (h in tracked or _is_tracker("//" + h))})
    results.append(_result("outside_eu_before_consent", not abroad,
                           "No tracking requests to companies outside the EU before a choice." if not abroad else
                           f"Before any choice, requests went to: {', '.join(abroad)}."))

    if notice_link and notice_text:
        items = notice_items(notice_text)
        missing = [i for i, ok, _ in items if not ok]
        results.append(_result("privacy_notice_content", not missing,
                               "Mentions everything Art. 13 lists (a person still needs to check the wording)."
                               if not missing else f"Doesn't seem to mention: {'; '.join(missing)}."))
    else:
        items = []
        results.append(_result("privacy_notice_content", False, "No privacy notice found to check."))

    if forms:
        bad = [f for f in forms if not f["https"] or not f["notice"] or f["ticked"]]
        results.append(_result("forms", not bad, f"{len(forms)} form(s) collect personal data; all are sent over HTTPS"
                               f"{' (not checked: an app on this computer)' if local else ''}, link the privacy notice and have no marketing box ticked in advance." if not bad else
                               f"{len(bad)} of {len(forms)} form(s) that collect personal data have a problem "
                               "(see the forms table)."))

    tables = [
        {"title": "GDPR and cookie checks", "columns": ["Check", "Result", "What was found", "Law"],
         "rows": [[r.title, "passed" if r.passed else "failed", r.detail, r.law] for r in results], "note": ""},
        _cookie_table(before, rejected, accepted, site_host),
        _third_party_table(before, rejected, accepted),
    ]
    if items:
        tables.append({"title": "What the privacy notice covers (GDPR Art. 13)", "columns": ["Item", "Mentioned?", "Words found"],
                       "rows": [[i, "yes" if ok else "no", words] for i, ok, words in items],
                       "note": "Found by looking for words, so a person still needs to read the notice."})
    if forms:
        tables.append({"title": "Forms that collect personal data", "columns":
                       ["Page", "Fields", "Sent over HTTPS?", "Privacy notice linked?", "Ticked in advance"],
                       "rows": [[urlparse(f["page"]).path or "/", ", ".join(f["fields"][:6]), ("local app" if local else "yes") if f["https"] else "no",
                                 "yes" if f["notice"] else "no", ", ".join(f["ticked"]) or "none"] for f in forms],
                       "note": "Forms are never submitted."})
    return Findings(results, tables)


def _cookie_table(before: Visit, rejected: Visit, accepted: Visit, site_host: str) -> dict:
    names = {}
    for when, v in (("before", before), ("reject", rejected), ("accept", accepted)):
        for c in v.cookies:
            entry = names.setdefault((c["name"], c["domain"].lstrip(".")), {"c": c, "when": set()})
            entry["when"].add(when)
    rows = []
    for (name, domain), e in sorted(names.items()):
        kind = ("remembers the cookie choice" if CONSENT_COOKIE.match(name) else
                "tracking" if TRACKING_COOKIE.match(name) else
                "other site's" if not _same_site(domain, site_host) else "the site's own")
        rows.append([name, domain, kind, _days(e["c"].get("expires", -1)),
                     "yes" if "before" in e["when"] else "no", "yes" if "reject" in e["when"] else "no",
                     "yes" if "accept" in e["when"] else "no"])
    return {"title": f"{len(rows)} cookie(s) seen", "columns":
            ["Cookie", "Set by", "Kind", "Lasts", "Before choosing", "After reject", "After accept"], "rows": rows,
            "note": "Tracking and other sites' cookies need consent; cookies that remember the choice itself don't."}


def _third_party_table(before: Visit, rejected: Visit, accepted: Visit) -> dict:
    hosts = sorted(set(before.third_party) | set(rejected.third_party) | set(accepted.third_party)
                   | {urlparse(u).hostname or "" for v in (before, rejected, accepted) for u in v.trackers})
    rows = []
    for h in hosts:
        if not h:
            continue
        who, where = company(h)
        seen = [h in v.third_party or any((urlparse(u).hostname or "") == h for u in v.trackers)
                for v in (before, rejected, accepted)]
        rows.append([h, who or "unknown", where or "unknown", *("yes" if s else "no" for s in seen),
                     "yes" if _is_tracker("//" + h) else "no"])
    return {"title": f"{len(rows)} other site(s) contacted", "columns":
            ["Address", "Company", "Based in", "Before choosing", "After reject", "After accept", "Known tracker?"],
            "rows": rows, "note": "Requests to known trackers were recorded and blocked, so this test sent no analytics."}
