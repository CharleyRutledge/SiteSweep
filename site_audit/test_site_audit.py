"""Site audit: every discovered page loads, has no broken links/images or script errors, works on a
phone, is quick enough, is served securely, and is scanned for accessibility (WCAG).

Every page is opened once (see conftest.crawl) and measured; each test lists all problems it finds there,
so one run shows the whole picture.
"""

from __future__ import annotations

import os
from urllib.parse import urlparse

import pytest
from playwright.sync_api import Error as PlaywrightError

from pages.base_page import BasePage
from site_audit.conftest import SKIP_LINKS, SiteMap, refused_by_this_network, same_site, short, show
from ui_automation import gdpr
from ui_automation.compliance import Monitor, as_dicts, check_page
from ui_automation.config import accepts_self_signed

# Sites that refuse automated link checks (they answer bots with these) are "unverified", not broken.
UNVERIFIABLE = {401, 403, 405, 406, 429, 999}
MAX_EXTERNAL_LINKS = 60
_IMPACT = ["none", "minor", "moderate", "serious", "critical"]


# What each check means, in plain words: shown above its results in the report.
ABOUT = {
    "test_crawl_found_the_site": "Finds the site's pages by following its own links from the home page. Every other "
                                 "check uses the pages found here.",
    "test_every_page_loads_with_a_title_and_heading": "Every page opens, shows real content, and has a page title "
                                                      "(shown in the browser tab, WCAG 2.4.2) and a main heading.",
    "test_no_javascript_errors": "No page has a script error that stops part of it working. Visitors don't see "
                                 "these errors, but the feature the script runs (menus, forms, buttons) may break.",
    "test_no_network_errors": "Everything a page loads (scripts, styles, images, fonts, data from the server) "
                              "arrives. A failed request usually means something missing or broken on the page.",
    "test_no_broken_links": "Every link on the site leads somewhere: no 'page not found' (HTTP 404) or server "
                            "errors.",
    "test_role_is_refused_restricted_pages": "Pages this kind of user must not see (listed in the settings) are "
                                             "refused to them.",
    "test_no_broken_images": "Every image on every page loads.",
    "test_pages_fit_every_screen_size": "No page needs sideways scrolling, from a small phone (320 px) to a desktop "
                                        "screen (WCAG 1.4.10 reflow).",
    "test_works_on_mobile_devices": "Every page opened as a real phone (screen, touch, mobile browser): set up for "
                                    "phones, no sideways scrolling, readable text, buttons big enough to tap.",
    "test_api_calls_work_and_are_fast": "Every request the pages make to the site's server for data (its API) "
                                        "answers without an error, and quickly.",
    "test_api_refuses_logged_out_requests": "The data this user's pages ask the server for is refused to someone "
                                            "who isn't logged in.",
    "test_api_keeps_roles_apart": "One kind of user can't read another kind of user's data from the server.",
    "test_pages_load_quickly": "How long each page takes until it can be used, compared with the limit in the "
                               "settings (audit.load_budget_ms).",
    "test_served_securely": "Safe security checks, done with ordinary requests anyone's browser makes (nothing "
                            "attack-like): HTTPS and its certificate, the security headers that protect visitors' "
                            "browsers, cookie protections, software versions given away, files loaded over plain "
                            "http, private files (.git, .env) left public, browsable folders, and which other sites "
                            "may read its data (CORS). Each result names the OWASP standard it comes from; SOC 2 "
                            "and HIPAA controls are mapped, not assessed.",
    "test_pages_are_accessible": "Every page checked against the accessibility standard (WCAG 2.1 AA, required in "
                                 "the EU) for people using screen readers, keyboards, zoom or other aids. The "
                                 "issues, with fixes, are in the Accessibility section.",
    "test_meets_website_requirements": "Irish and EU legal must-haves on the home page, checked before any cookies "
                                       "are accepted: a privacy notice, no tracking before consent and a way to "
                                       "refuse it, an accessibility statement, company details and contact details. "
                                       "Each result is in the Website requirements section.",
    "test_language_and_translations_are_right": "Each page says which language it is in (so screen readers "
                                                "pronounce it right) and is in that language; no translation keys, "
                                                "{{placeholders}} or garbled characters showing. For a site in "
                                                "several languages, every language version is linked correctly "
                                                "(hreflang), opens, is really translated, links back, fits a "
                                                "phone, and can be reached from a language switcher.",
    "test_follows_gdpr_and_cookie_rules": "GDPR and cookie rules, checked the way the European Data Protection "
                                          "Board's website auditing tool does it: the site is opened three times in a fresh "
                                          "browser (no choice made, after \"Reject\", after \"Accept\") and every "
                                          "cookie, stored item and other site contacted is recorded. Then the cookie "
                                          "banner, the privacy notice and forms asking for personal data are checked. "
                                          "Nothing is submitted, and requests to trackers are blocked.",
}


def evidence(request: pytest.FixtureRequest, title: str, columns: list[str], rows: list[list], note: str = "") -> None:
    """A table of what a check found, shown in the report whether the check passed or failed."""
    if not hasattr(request.node, "evidence"):
        request.node.evidence = []
    request.node.evidence.append({"title": title, "columns": columns, "note": note,
                                  "rows": [[str(c) for c in row] for row in rows]})


def _split(problem: str) -> list[str]:
    """'GET /a.js -> HTTP 404' -> ['GET /a.js', 'HTTP 404']."""
    what, _, result = problem.partition(" -> ")
    return [what, result or ""]


def report(problems: list[str], what: str) -> None:
    if problems:
        raise AssertionError(f"{len(problems)} {what}:\n" + "\n".join(f"- {p}" for p in problems))


def loaded(site_map: SiteMap) -> list:
    """Results of the pages that opened (in crawl order)."""
    return [r for u in site_map.pages if (r := site_map.results.get(u)) and not r.load_error]


def test_crawl_found_the_site(audit: SiteMap, request: pytest.FixtureRequest) -> None:
    show(request, audit, audit.pages)  # every page found, as a gallery in the report
    evidence(request, f"{len(audit.pages)} page(s) found", ["Page", "Title"],
             [[short(u, audit.home), (audit.results[u].title if u in audit.results else "")] for u in audit.pages])
    where = f" under {audit.area}" if audit.area else ""
    print(f"Found {len(audit.pages)} page(s){where} and {len(audit.links)} link(s)")
    if audit.skipped_public:
        print(f"Pages the logged-out visitor already checked were not opened again ({audit.skipped_public}).")
    assert audit.pages, "the home page could not be opened"
    problems = [f"{short(u, audit.home)}: {why}" for u, why in audit.problems.items()]
    if audit.role != "public" and len(audit.pages) == 1:
        # Signed-in pages reached through buttons (not <a href> links) cannot be found by following links.
        problems.append(f"only the start page {short(audit.pages[0], audit.home)} was found for role "
                        f"'{audit.role}': it has no ordinary links to other signed-in pages, so the rest of the "
                        f"app was not checked. List those pages in auth.roles.{audit.role}.pages")
    report(problems, "crawl problem(s)")


def test_every_page_loads_with_a_title_and_heading(audit: SiteMap, request: pytest.FixtureRequest) -> None:
    problems: list[str] = []
    bad: list[str] = []
    for url in audit.pages:
        r = audit.results.get(url)
        where = short(url, audit.home)
        if r is None:
            continue
        if r.load_error:
            problems.append(f"{where}: did not load ({r.load_error})")
            continue
        if r.status is not None and r.status >= 400:
            problems.append(f"{where}: HTTP {r.status}")
            bad.append(url)
            continue
        if r.blank_ms:
            problems.append(f"{where}: still blank or loading after {r.blank_ms / 1000:g} s, so its content could "
                            "not be checked (a slow or failed API call? audit.content_wait_ms waits longer)")
            bad.append(url)
            continue
        if not r.title:
            problems.append(f"{where}: no page title (WCAG 2.4.2)")
            bad.append(url)
        if r.h1_count == 0:
            problems.append(f"{where}: no main heading (h1)")
            bad.append(url)
    show(request, audit, list(dict.fromkeys(bad)))
    rows = [[short(u, audit.home), r.title or "(none)", "yes" if r.h1_count else "no",
             r.load_error or (f"HTTP {r.status}" if r.status else "")]
            for u in audit.pages if (r := audit.results.get(u))]
    evidence(request, "Every page", ["Page", "Title", "Main heading", "Problem"], rows)
    report(problems, "page problem(s)")


def test_no_javascript_errors(audit: SiteMap, request: pytest.FixtureRequest) -> None:
    problems = [f"{short(r.url, audit.home)}: {err}" for r in loaded(audit) for err in r.js_errors]
    show(request, audit, [r.url for r in loaded(audit) if r.js_errors])
    evidence(request, f"{len(problems)} script error(s) on {len(loaded(audit))} page(s) checked", ["Page", "Error"],
             [[short(r.url, audit.home), err] for r in loaded(audit) for err in r.js_errors],
             "The screenshots show each page that had an error.")
    report(problems, "uncaught JavaScript error(s)")


def test_no_network_errors(audit: SiteMap, request: pytest.FixtureRequest) -> None:
    """Every request a page makes (scripts, styles, images, fonts, API calls) must get an answer below HTTP 400."""
    problems = [f"{short(r.url, audit.home)}: {err}" for r in loaded(audit) for err in r.network_errors]
    show(request, audit, [r.url for r in loaded(audit) if r.network_errors])
    evidence(request, f"{len(problems)} failed request(s) on {len(loaded(audit))} page(s) checked",
             ["Page", "Request", "Result"],
             [[short(r.url, audit.home), *_split(err)] for r in loaded(audit) for err in r.network_errors],
             "HTTP 4xx: the file or address doesn't exist or is refused. HTTP 5xx: the server failed. "
             "'No answer': nothing came back (blocked, offline or timed out).")
    report(problems, "failed network request(s)")


def test_no_broken_links(site: BasePage, site_map: SiteMap, request: pytest.FixtureRequest) -> None:
    home = site_map.home
    # Logout / delete links are never requested: they could end the role's session or change data.
    internal = [u for u in site_map.links if same_site(u, home) and not SKIP_LINKS.search(urlparse(u).path)]
    external = [u for u in site_map.links if not same_site(u, home)][:MAX_EXTERNAL_LINKS]
    if not site.settings.audit.check_external_links:
        external = []
    site.goto_path(home)
    site.step(f"Check {len(internal)} internal and {len(external)} external link(s)")
    broken, unverified, not_reached = [], [], []
    broken_rows: list[tuple[str, str]] = []
    for url in internal + external:
        try:
            r = site.page.request.get(url, timeout=20_000, max_redirects=10, fail_on_status_code=False)
            status = r.status
        except PlaywrightError as exc:
            broken.append(f"{url} (linked from {short(site_map.links[url], home)}): {exc.message.splitlines()[0][:120]}")
            broken_rows.append((url, f"no answer ({exc.message.splitlines()[0][:120]})"))
            continue
        if status == 403 and refused_by_this_network(r):
            not_reached.append(f"{url}: this computer's network doesn't allow {urlparse(url).hostname}")
        elif status in UNVERIFIABLE and not same_site(url, home):
            unverified.append(f"{url}: HTTP {status}")
        elif status >= 400:
            broken.append(f"{url} (linked from {short(site_map.links[url], home)}): HTTP {status}")
            broken_rows.append((url, f"HTTP {status}" + (" (page not found)" if status == 404 else "")))
    if unverified:
        print("Links that refuse automated checks (not counted as broken):\n" + "\n".join(unverified))
    evidence(request, f"{len(broken)} broken link(s) of {len(internal) + len(external)} checked "
             f"({len(internal)} on the site, {len(external)} to other sites)", ["Link", "Linked from", "Result"],
             [[u, short(site_map.links[u], home), why] for u, why in broken_rows])
    if unverified:
        evidence(request, "Not counted as broken: these sites refuse automated checks", ["Link", "Answer"],
                 [u.rsplit(": ", 1) for u in unverified])
    if not_reached:
        evidence(request, "Not checked: this computer's network doesn't allow these sites", ["Link", "Reason"],
                 [u.split(": ", 1) for u in not_reached],
                 "Not the site's fault. In Claude Code on the web, allow these domains in the network access.")
    if not_reached:
        print("Links not checked, because this computer's network refused them (not the site's fault; in Claude Code "
              "on the web, allow these domains in the environment's network access):\n" + "\n".join(not_reached))
    report(broken, "broken link(s)")


def test_role_is_refused_restricted_pages(audit: SiteMap, request: pytest.FixtureRequest) -> None:
    """auth.roles.<role>.must_not_access: these pages must refuse this role (HTTP 401/403/404 or the login page)."""
    opened = [f"{path}: {what}" for path, what in audit.refused.items() if what]
    print("\n".join(f"{path}: refused" for path, what in audit.refused.items() if not what))
    evidence(request, f"Pages role '{audit.role}' must not see", ["Page", "Result"],
             [[path, what or "refused (good)"] for path, what in audit.refused.items()])
    report(opened, f"page(s) that role '{audit.role}' should not be able to open")


def test_no_broken_images(audit: SiteMap, request: pytest.FixtureRequest) -> None:
    problems = [f"{short(r.url, audit.home)}: {src[:150]}" for r in loaded(audit) for src in r.broken_images]
    show(request, audit, [r.url for r in loaded(audit) if r.broken_images])
    evidence(request, f"{len(problems)} broken image(s) on {len(loaded(audit))} page(s) checked", ["Page", "Image"],
             [[short(r.url, audit.home), src[:150]] for r in loaded(audit) for src in r.broken_images])
    report(problems, "broken image(s)")


def test_pages_fit_every_screen_size(audit: SiteMap, settings, request: pytest.FixtureRequest) -> None:
    """WCAG 1.4.10 (reflow) and responsive layout: at every size in audit.screens (320 px phone to desktop)
    nothing may need sideways scrolling. A screenshot is kept at each size where a page does not fit."""
    sizes = ", ".join(f"{s.name} {s.width}px" for s in settings.audit.screens)
    print(f"Checked at: {sizes}")
    problems = []
    for r in loaded(audit):
        if not r.overflow:
            continue
        sizes = "; ".join(f"on {w['screen']} it is {w['width']}px wide (widest element: {w['name']})"
                          for w in r.overflow.values())
        problems.append(f"{short(r.url, audit.home)}: {sizes}")
        for wide in r.overflow.values():
            if wide.get("shot"):
                request.node.step_screenshots.append((f"{short(r.url, audit.home)} on {wide['screen']}", wide["shot"]))
    evidence(request, f"{len(problems)} of {len(loaded(audit))} page(s) need sideways scrolling",
             ["Page", "Screen", "Page width", "Widest element (the likely cause)"],
             [[short(r.url, audit.home), w["screen"], f"{w['width']} px", w["name"]]
              for r in loaded(audit) for w in r.overflow.values()],
             f"Checked at: {', '.join(f'{s.name} {s.width} px' for s in settings.audit.screens)}. "
             "The screenshots show each page at the size where it doesn't fit.")
    report(problems, "page(s) that need sideways scrolling")


def test_works_on_mobile_devices(audit: SiteMap, settings, playwright, run_dir, request: pytest.FixtureRequest) -> None:
    """Every page on real phone profiles (audit.mobile_devices: iPhone, Android): set up for phones, no sideways
    scrolling, readable text, buttons big enough to tap, and no errors. Devices take turns by day like browsers."""
    from site_audit.conftest import check_on_device
    from ui_automation.browsers import browsers_for_run

    devices = browsers_for_run(list(settings.audit.mobile_devices), settings.browser_rotation)
    unusable = [e for e in os.environ.get("WEB_UI_UNUSABLE_ENGINES", "").split(",") if e]
    if unusable:  # their browser can't work on this computer: listed under "Not run"
        devices = [d for d in devices if playwright.devices.get(d, {}).get("default_browser_type") not in unusable]
    print(f"Checked on: {', '.join(devices) or 'none (see Not run)'}")
    problems: list[str] = []
    for device in devices:
        found, gallery = check_on_device(playwright, settings, audit, device,
                                         run_dir / "screenshots" / f"mobile-{audit.role}")
        problems += found
        request.node.step_screenshots.extend(gallery)
    evidence(request, f"{len(problems)} problem(s) on {', '.join(devices) or 'no phone'}", ["Problem"],
             [[p] for p in problems])
    report(problems, "mobile problem(s)")


def test_api_calls_work_and_are_fast(audit: SiteMap, settings, request: pytest.FixtureRequest) -> None:
    """Every API call the pages made (fetch / XHR) answered below HTTP 400, within audit.api_budget_ms."""
    from site_audit.api import where

    budget = settings.audit.api_budget_ms
    calls = audit.api
    print(f"{len(calls)} API call(s) seen" + (":\n" + "\n".join(
        f"{c.method} {where(c, audit.home)} -> HTTP {c.status} in {c.ms} ms" for c in calls[:60]) if calls else ""))
    problems = [f"{c.method} {where(c, audit.home)} -> HTTP {c.status} (on {short(c.page, audit.home)})"
                for c in calls if c.status >= 400]
    problems += [f"{c.method} {where(c, audit.home)} took {c.ms} ms (budget {budget} ms, on {short(c.page, audit.home)})"
                 for c in calls if c.status < 400 and c.ms > budget]
    evidence(request, f"{len(calls)} API call(s) seen (limit {budget} ms)", ["Request", "Page", "Answer", "Time", "OK?"],
             [[f"{c.method} {where(c, audit.home)}", short(c.page, audit.home), f"HTTP {c.status}", f"{c.ms} ms",
               "yes" if c.status < 400 and c.ms <= budget else "no"] for c in calls[:200]])
    report(problems, "API problem(s)")


def test_api_refuses_logged_out_requests(audit: SiteMap, settings, playwright, browser, run_dir) -> None:
    """Every read request this role's pages made is sent again with no login (no cookies, no token). Handing
    back the same data is a security hole. Endpoints the logged-out visitor uses, or audit.public_api, are fine."""
    from site_audit.api import is_public, replay, replayable, where
    from site_audit.conftest import _map_for

    public = _map_for(browser, settings, run_dir, "public") if settings.auth.include_public else None
    problems, refused, notes = [], [], []
    for call in replayable(audit):
        if is_public(call, settings, public):
            continue
        r = replay(playwright, settings, call, as_site=None)
        label = f"GET {where(call, audit.home)}"
        if r.same_data:
            problems.append(f"{label}: answers without logging in, with the same data role '{audit.role}' gets "
                            f"(HTTP {r.status}; if it is meant to be public, list it in audit.public_api)")
        elif 200 <= r.status < 300:
            notes.append(f"{label}: HTTP {r.status} without logging in, but with different data")
        else:
            refused.append(f"{label}: refused (HTTP {r.status}{', ' + r.error if r.error else ''})")
    print("\n".join(refused + notes) or "No private read requests to check.")
    report(problems, f"API request(s) that work without logging in (role '{audit.role}')")


def test_api_keeps_roles_apart(audit: SiteMap, settings, playwright, browser, run_dir) -> None:
    """This role's read requests are sent again as every other role. Another role getting the same data for
    a request its own pages never make points to a leak between roles (e.g. a viewer reading an admin's data)."""
    from site_audit.api import is_public, path, replay, replayable, where
    from site_audit.conftest import _map_for

    public = _map_for(browser, settings, run_dir, "public") if settings.auth.include_public else None
    problems, checked = [], 0
    for other in (r.name for r in settings.auth.roles if r.name != audit.role):
        theirs = _map_for(browser, settings, run_dir, other)
        if theirs.login_error:
            problems.append(f"role '{other}' could not log in, so it was not checked against '{audit.role}'")
            continue
        their_paths = {path(c.url) for c in theirs.api}
        for call in replayable(audit):
            if is_public(call, settings, public) or path(call.url) in their_paths:
                continue  # public, or something the other role's own pages use too
            checked += 1
            r = replay(playwright, settings, call, as_site=theirs)
            if r.same_data:
                problems.append(f"role '{other}' can read role '{audit.role}''s GET {where(call, audit.home)} "
                                f"(the same data, HTTP {r.status}; '{other}''s own pages never ask for it)")
    print(f"{checked} request(s) of role '{audit.role}' replayed as the other role(s)")
    report(problems, "possible leak(s) between roles")


def test_pages_load_quickly(audit: SiteMap, settings, request: pytest.FixtureRequest) -> None:
    budget = settings.audit.load_budget_ms
    timed = [r for r in loaded(audit) if r.ready_ms is not None]
    print("\n".join(f"{short(r.url, audit.home)}: usable after {r.ready_ms} ms" for r in timed))
    slow = [r for r in timed if r.ready_ms > budget]
    show(request, audit, [r.url for r in slow])
    evidence(request, f"{len(slow)} of {len(timed)} page(s) slower than the limit of {budget} ms",
             ["Page", "Usable after", "Within the limit?"],
             [[short(r.url, audit.home), f"{r.ready_ms / 1000:.1f} s", "yes" if r.ready_ms <= budget else "no"]
              for r in sorted(timed, key=lambda r: -r.ready_ms)],
             "'Usable after': from opening the page until its content was shown and stopped changing.")
    report([f"{short(r.url, audit.home)}: usable after {r.ready_ms} ms (budget {budget} ms)" for r in slow],
           "slow page(s)")


def test_served_securely(site: BasePage, site_map: SiteMap, role: str, request: pytest.FixtureRequest) -> None:
    """Safe security checks (ui_automation/security.py): ordinary GET requests, nothing attack-like."""
    from ui_automation import security

    site.step("Check HTTPS, certificate, headers, cookies and well-known private files")
    found = security.audit(site.page.request, site.page, site_map.home, [r.url for r in loaded(site_map)],
                           api=[c.url for c in site_map.api if c.method == "GET"][:3],
                           check_certificate=not accepts_self_signed(site.settings))
    for table in found.tables:
        evidence(request, table["title"], table["columns"], table["rows"], table["note"])
    report([f"[{f.severity}] {f.title}: {f.detail} ({f.standards})" for f in found.findings if f.fails],
           "security finding(s)")


def test_pages_are_accessible(audit: SiteMap, settings, request: pytest.FixtureRequest) -> None:
    """Every page scanned with axe-core; findings (with fixes) are in the report's Accessibility section."""
    from ui_automation.accessibility import at_or_above

    cfg = settings.accessibility
    pages = loaded(audit)
    request.node.accessibility = [
        {"url": r.url, "standard": cfg.standard, "violations": [v.__dict__ for v in r.accessibility]} for r in pages
    ]
    # Grouped by issue, not by page: the same issue on most pages is one fix in a shared header, footer or style.
    by_rule: dict[str, dict] = {}
    if cfg.fail_on != "none":
        for r in pages:
            for v in at_or_above(r.accessibility, cfg.fail_on):
                entry = by_rule.setdefault(v.rule, {"v": v, "pages": []})
                entry["pages"].append(short(r.url, audit.home))
    failures = []
    for entry in sorted(by_rule.values(), key=lambda e: -len(e["pages"])):
        v, where = entry["v"], entry["pages"]
        crit = f" (WCAG {', '.join(v.criteria)})" if v.criteria else ""
        listed = ", ".join(where[:5]) + (f" and {len(where) - 5} more" if len(where) > 5 else "")
        shared = (" - on most pages, so probably one fix in a shared header, footer or style"
                  if len(pages) > 2 and len(where) >= 0.6 * len(pages) else "")
        example = f"; e.g. {v.targets[0]}" if v.targets else ""
        failures.append(f"[{v.impact}] {v.help}{crit}: {len(where)} page(s): {listed}{example}{shared}")
    show(request, audit, [r.url for r in pages if r.accessibility])
    evidence(request, f"Issues per page ({len(pages)} page(s) checked)", ["Page", "Issues", "Most serious"],
             [[short(r.url, audit.home), str(len(r.accessibility)),
               max((v.impact for v in r.accessibility), key=_IMPACT.index, default="none")] for r in pages],
             "Each issue, who it affects and how to fix it is in the Accessibility section.")
    report(failures, f"accessibility issue type(s) at or above '{cfg.fail_on}' (fixes are in the report)")


def test_meets_website_requirements(site: BasePage, site_map: SiteMap, request, role: str) -> None:
    """Irish / EU website requirements on the home page, checked before any cookie consent is given."""
    monitor = Monitor(site.page)  # before navigation: nothing may track before consent
    site.goto_path(site_map.home)
    site.page.wait_for_load_state("load")
    site.wait_until_settled()
    site.step("Check website requirements (before any consent is given)")
    results = check_page(site.page, monitor, site.settings.compliance.checks)
    request.node.compliance = [{"url": site.page.url, "results": as_dicts(results)}]
    failed = [f"{r.title}: {r.detail} ({r.law})" for r in results if not r.passed]
    if not site.settings.compliance.report_only:
        report(failed, "website requirement(s) not met")


def test_follows_gdpr_and_cookie_rules(audit: SiteMap, browser, settings, request: pytest.FixtureRequest) -> None:
    """GDPR and ePrivacy (cookie) checks on the home page and the pages most likely to ask for personal data, as
    a new visitor who hasn't chosen anything yet."""
    urls = gdpr.pick_pages([r.url for r in loaded(audit)], settings.compliance.gdpr_pages) or [audit.home]
    found = gdpr.audit(browser, urls, {"ignore_https_errors": accepts_self_signed(settings)})
    for table in found.tables:
        evidence(request, table["title"], table["columns"], table["rows"], table["note"])
    request.node.compliance = [{"url": f"{short(urls[0], audit.home)} - GDPR and cookies ({len(urls)} page(s))",
                                "results": as_dicts(found.results)}]
    failed = [f"{r.title}: {r.detail} ({r.law})" for r in found.results if not r.passed]
    if not settings.compliance.report_only:
        report(failed, "GDPR or cookie rule(s) not followed")


def test_language_and_translations_are_right(audit: SiteMap, site: BasePage, request: pytest.FixtureRequest) -> None:
    """Localization (ui_automation/localization.py) on up to 5 pages, then every language version of the home page."""
    from ui_automation import localization

    site.step("Check languages and translations")
    found = localization.audit(site.page, site.page.request, [r.url for r in loaded(audit)][:5])
    for table in found.tables:
        evidence(request, table["title"], table["columns"], table["rows"], table["note"])
    for f in found.findings:
        print(f"{'passed' if f.passed else 'FAILED'}: {f.title}: {f.detail}")
    report([f"{f.title}: {f.detail} ({f.law})" for f in found.findings if not f.passed],
           "language or translation problem(s)")
