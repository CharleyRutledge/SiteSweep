"""Safe security checks: what anyone's browser can already see, read with ordinary GET requests.

Nothing attack-like: no logins tried, no forms submitted, no injected input, no scanning of ports or guessing of
pages beyond a short fixed list of well-known files that should never be public (a site's own .git folder or .env
file). When one of those is found, the report says so and how big it is, never what is in it.

Each finding has a severity and the standards it relates to: the OWASP Application Security Verification Standard
(ASVS 4.0.3) and Top 10 (2021). SOC 2 and HIPAA are only mapped (the controls a finding is evidence for), never
assessed: those need an auditor.
"""

from __future__ import annotations

import os
import re
import socket
import ssl
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urljoin, urlparse

SEVERITIES = ["info", "low", "medium", "high"]  # info never fails a run: it is advice

STANDARDS = {
    "https": "OWASP Top 10 A02:2021; ASVS 9.1.1; SOC 2 CC6.7; HIPAA 164.312(e)(1)",
    "certificate": "ASVS 9.1.1; SOC 2 CC6.7; HIPAA 164.312(e)(1)",
    "hsts": "ASVS 14.4.5; OWASP Top 10 A05:2021",
    "nosniff": "ASVS 14.4.4; OWASP Top 10 A05:2021",
    "referrer": "ASVS 14.4.6",
    "clickjacking": "ASVS 14.4.7; OWASP Top 10 A05:2021",
    "csp": "ASVS 14.4.3; OWASP Top 10 A03:2021 (limits the harm of injected scripts)",
    "permissions": "OWASP Secure Headers Project",
    "versions": "ASVS 14.3.3; OWASP Top 10 A05:2021",
    "cookies": "ASVS 3.4.1, 3.4.2, 3.4.3; SOC 2 CC6.1",
    "mixed_content": "ASVS 9.1.1; SOC 2 CC6.7; HIPAA 164.312(e)(1)",
    "exposed_files": "ASVS 4.3.2; OWASP Top 10 A05:2021; SOC 2 CC6.1",
    "directory_listing": "ASVS 4.3.2; OWASP Top 10 A05:2021",
    "cors": "ASVS 14.5.3; OWASP Top 10 A01:2021",
    "security_txt": "RFC 9116",
}
TITLES = {
    "https": "Served over HTTPS", "certificate": "Valid certificate, not about to expire",
    "hsts": "Browsers kept on HTTPS (HSTS)", "nosniff": "File types can't be misread (nosniff)",
    "referrer": "Addresses not leaked to other sites (Referrer-Policy)",
    "clickjacking": "Can't be hidden inside another site (clickjacking)",
    "csp": "Content Security Policy", "permissions": "Permissions-Policy",
    "versions": "Software versions not given away", "cookies": "Cookies protected",
    "mixed_content": "Nothing loaded over plain http", "exposed_files": "No private files public",
    "directory_listing": "Folders can't be browsed", "cors": "Other sites can't read its data (CORS)",
    "security_txt": "A way to report security problems (security.txt)",
}
WHY = {
    "https": "Without HTTPS, anyone on the same network (café Wi-Fi) can read and change what visitors see and send.",
    "certificate": "An expired or untrusted certificate makes browsers show a full-page warning instead of the site.",
    "hsts": "Tells browsers to always use HTTPS, so a first visit can't be quietly switched to plain http.",
    "nosniff": "Stops browsers treating an uploaded file as a script.",
    "referrer": "Stops full page addresses (which can hold names or tokens) being sent to other sites.",
    "clickjacking": "Stops another site showing this one invisibly and tricking people into clicking on it.",
    "csp": "Limits where scripts can come from, so an injected script can't run.",
    "permissions": "Turns off browser features (camera, microphone, location) the site doesn't use.",
    "versions": "Exact version numbers tell attackers which known weaknesses to try.",
    "cookies": "Login cookies need Secure (HTTPS only), HttpOnly (scripts can't steal them) and SameSite.",
    "mixed_content": "Anything loaded over plain http on an HTTPS page can be read or changed on the way.",
    "exposed_files": "Source code history and settings files often hold passwords and keys.",
    "directory_listing": "A browsable folder shows every file in it, including ones never linked.",
    "cors": "A loose CORS setting lets any website read this site's data with the visitor's login.",
    "security_txt": "Tells people who find a problem how to report it (recommended, not required).",
}

# Well-known files that must never be public, and what their contents look like (so a "page not found" page that
# answers 200 is never mistaken for one).
EXPOSED = [
    ("/.git/HEAD", "the site's source code history (.git)", "high",
     lambda b: re.match(rb"^(ref: refs/|[0-9a-f]{40}\s*$)", b) is not None),
    ("/.env", "a settings file (.env), which usually holds passwords and keys", "high",
     lambda b: not _html(b) and len(re.findall(rb"(?m)^[A-Z][A-Z0-9_]{2,}=", b)) >= 2),
    ("/.htpasswd", "a password file (.htpasswd)", "high",
     lambda b: not _html(b) and re.search(rb"(?m)^[\w.-]+:(\$apr1\$|\$2[aby]\$|\{SHA\}|[./0-9A-Za-z]{13}$)", b) is not None),
    ("/wp-config.php.bak", "a WordPress settings backup (wp-config.php.bak)", "high", lambda b: b"DB_PASSWORD" in b),
    ("/server-status", "the web server's status page (who is visiting, right now)", "medium",
     lambda b: b"Apache Server Status" in b),
    ("/phpinfo.php", "a PHP information page (versions and settings)", "medium",
     lambda b: b"phpinfo()" in b and b"PHP Version" in b),
    ("/.DS_Store", "a Mac folder index (.DS_Store) listing the folder's files", "low",
     lambda b: b[4:8] == b"Bud1"),
]
SESSION_COOKIE = re.compile(r"sess|sid$|^sid|token|auth|jwt|login|remember", re.I)
JS_READABLE = re.compile(r"csrf|xsrf", re.I)  # meant to be read by the page's scripts
VERSION = re.compile(r"\d+\.\d+")
LISTING = re.compile(rb"<title>\s*(Index of /|Directory listing for /)", re.I)
TEST_ORIGIN = "https://sitesweep-cors-check.invalid"
# Addresses the page's own tags load or send to. Read from the page itself: browsers upgrade or block plain-http
# files on HTTPS pages before any request is made, so requests alone would miss them.
RESOURCES_JS = """() => {
    const out = [];
    const add = (what, url) => { if (url) out.push([what, url]); };
    document.querySelectorAll('script[src], img[src], iframe[src], audio[src], video[src], source[src], embed[src]')
        .forEach(e => add(e.tagName.toLowerCase(), e.src));
    document.querySelectorAll('link[rel~=stylesheet][href], link[rel~=icon][href]').forEach(e => add('link', e.href));
    document.querySelectorAll('form').forEach(f => add('form', f.action));
    return out;
}"""


def _html(body: bytes) -> bool:
    return bool(re.search(rb"<(!doctype|html|head|body)\b", body[:2000], re.I))


@dataclass
class Finding:
    check: str
    severity: str  # "ok" when nothing is wrong, else one of SEVERITIES
    detail: str

    @property
    def title(self) -> str:
        return TITLES[self.check]

    @property
    def standards(self) -> str:
        return STANDARDS[self.check]

    @property
    def fails(self) -> bool:
        return self.severity not in ("ok", "info")


@dataclass
class Results:
    findings: list[Finding] = field(default_factory=list)
    tables: list[dict] = field(default_factory=list)

    def add(self, check: str, severity: str, detail: str) -> None:
        self.findings.append(Finding(check, severity, detail))


def _get(request: Any, url: str, **kw: Any) -> Any:
    try:
        return request.get(url, fail_on_status_code=False, timeout=15_000, **kw)
    except Exception:  # noqa: BLE001 - no answer is reported by the check that needed one
        return None


def _set_cookies(response: Any) -> list[str]:
    return [h["value"] for h in response.headers_array if h["name"].lower() == "set-cookie"]


def parse_cookie(header: str) -> dict:
    name = header.split("=", 1)[0].strip()
    attrs = {a.split("=", 1)[0].strip().lower(): (a.split("=", 1)[1].strip() if "=" in a else "")
             for a in header.split(";")[1:]}
    return {"name": name, "secure": "secure" in attrs, "httponly": "httponly" in attrs,
            "samesite": attrs.get("samesite", "")}


def certificate_days(host: str, port: int = 443, timeout: float = 10.0) -> tuple[int | None, str]:
    """Days until the site's certificate expires, or (None, why it couldn't be checked or isn't trusted)."""
    context = ssl.create_default_context()
    try:
        with socket.create_connection((host, port), timeout=timeout) as raw, \
                context.wrap_socket(raw, server_hostname=host) as tls:
            not_after = tls.getpeercert()["notAfter"]
    except ssl.SSLCertVerificationError as exc:
        return None, f"not trusted: {exc.verify_message}"
    except (OSError, ssl.SSLError) as exc:
        return None, f"could not connect: {exc}"
    expires = datetime.fromtimestamp(ssl.cert_time_to_seconds(not_after), timezone.utc)
    return (expires - datetime.now(timezone.utc)).days, expires.strftime("%d %b %Y")


def behind_a_proxy() -> bool:
    return any(os.environ.get(n) for n in ("HTTPS_PROXY", "https_proxy"))


def audit(request: Any, page: Any, home: str, pages: list[str], api: list[str] | None = None,
          check_certificate: bool = True) -> Results:
    """Every check on the site at `home`. `request` sends GETs (with the browser's proxy and cookies); `page`
    opens up to five of `pages` to see what they load; `api` are the API addresses the pages called."""
    out = Results()
    host = urlparse(home).hostname or ""
    secure = home.startswith("https://")

    # HTTPS, and plain http sent on to it.
    if not secure:
        out.add("https", "high", "the site is not served over HTTPS")
    else:
        r = _get(request, f"http://{host}/", max_redirects=5)
        if r is None:
            out.add("https", "ok", f"Served over HTTPS; http://{host}/ doesn't answer at all.")
        elif not r.url.startswith("https://"):
            out.add("https", "high", f"http://{host}/ does not redirect to HTTPS (ended at {r.url})")
        else:
            out.add("https", "ok", f"Served over HTTPS, and http://{host}/ redirects to it.")

    if secure and check_certificate:
        if behind_a_proxy():
            out.add("certificate", "info", "Not checked: this computer's network re-signs HTTPS, so the site's own "
                                           "certificate can't be seen from here.")
        else:
            days, note = certificate_days(host, urlparse(home).port or 443)
            if days is None:
                out.add("certificate", "high", f"The certificate is {note}" if note.startswith("not") else
                        f"Not checked: {note}")
            elif days < 0:
                out.add("certificate", "high", f"The certificate expired on {note}.")
            elif days < 14:
                out.add("certificate", "medium", f"The certificate expires in {days} day(s), on {note}.")
            elif days < 30:
                out.add("certificate", "low", f"The certificate expires in {days} day(s), on {note}: renew it soon.")
            else:
                out.add("certificate", "ok", f"Trusted, and valid until {note} ({days} days).")

    response = _get(request, home)
    headers = {k.lower(): v for k, v in response.headers.items()} if response is not None else {}
    _headers(out, headers, secure)

    # Cookies the site sets itself, on the pages (as this role).
    cookie_rows: list[list[str]] = []
    seen: set[str] = set()
    for url in pages[:5]:
        r = response if url == home and response is not None else _get(request, url)
        for header in _set_cookies(r) if r is not None else []:
            c = parse_cookie(header)
            if c["name"] in seen:
                continue
            seen.add(c["name"])
            session = bool(SESSION_COOKIE.search(c["name"])) and not JS_READABLE.search(c["name"])
            problems = []
            if secure and not c["secure"]:
                problems.append("no Secure")
            if session and not c["httponly"]:
                problems.append("no HttpOnly")
            if not c["samesite"]:
                problems.append("no SameSite")
            cookie_rows.append([c["name"], _path(url), "yes" if c["secure"] else "no",
                                "yes" if c["httponly"] else "no", c["samesite"] or "not set",
                                ", ".join(problems) or "fine"])
    bad = [row for row in cookie_rows if row[5] != "fine"]
    login = [row for row in bad if "no Secure" in row[5] or "no HttpOnly" in row[5]]
    if not cookie_rows:
        out.add("cookies", "ok", "The site sets no cookies of its own on these pages.")
    else:
        out.add("cookies", "medium" if login else "low" if bad else "ok",
                f"{len(cookie_rows)} cookie(s), all with the protections they need." if not bad else
                "; ".join(f"{row[0]}: {row[5]}" for row in bad[:8]))

    # What the pages load, and forms that would send over plain http.
    insecure: list[list[str]] = []
    listing_dirs: set[str] = set()
    for url in pages[:5]:
        try:
            page.goto(url, wait_until="load", timeout=30_000)
            used = page.evaluate(RESOURCES_JS)
        except Exception:  # noqa: BLE001 - a page that won't open is the page checks' business
            used = []
        if secure:
            insecure += [[_path(url), u[:150], "form sends over http" if what == "form" else f"{what} over http"]
                         for what, u in used if u.startswith("http://")]
        for _, u in used:
            p = urlparse(u)
            if p.hostname == host and "/" in p.path.strip("/"):
                listing_dirs.add(f"{p.scheme}://{p.netloc}{p.path.rsplit('/', 1)[0]}/")
    if secure:
        out.add("mixed_content", "medium" if insecure else "ok",
                f"{len(insecure)} item(s) over plain http (see the table)." if insecure else
                "Every file and form on these pages uses HTTPS.")

    # Well-known private files.
    exposed_rows = []
    for path, what, severity, looks_right in EXPOSED:
        r = _get(request, urljoin(home, path), max_redirects=0)
        body = b""
        if r is not None and r.status == 200:
            try:
                body = r.body()[:200_000]
            except Exception:  # noqa: BLE001
                body = b""
        found = bool(body) and looks_right(body)
        exposed_rows.append([path, f"PUBLIC ({len(body)} bytes; contents not shown)" if found else
                             (f"not public (HTTP {r.status})" if r is not None else "no answer")])
        if found:
            out.add("exposed_files", severity, f"{path} is public: {what}. Remove it from the web server.")
    if not any(f.check == "exposed_files" for f in out.findings):
        out.add("exposed_files", "ok", f"None of {len(EXPOSED)} well-known private files is public.")

    # Folders of the site's own files.
    listed = []
    for d in sorted(listing_dirs)[:3]:
        r = _get(request, d)
        if r is not None and r.status == 200:
            try:
                if LISTING.search(r.body()[:5000]):
                    listed.append(_path(d))
            except Exception:  # noqa: BLE001
                pass
    out.add("directory_listing", "medium" if listed else "ok",
            f"These folders list their files: {', '.join(listed)}." if listed else
            f"{min(len(listing_dirs), 3)} folder(s) of the site's files checked; none lists its files.")

    _cors(out, request, home, api or [])

    r = _get(request, urljoin(home, "/.well-known/security.txt"))
    text = ""
    if r is not None and r.status == 200:
        try:
            text = r.text()[:20_000]
        except Exception:  # noqa: BLE001
            text = ""
    if re.search(r"(?mi)^contact:", text):
        out.add("security_txt", "ok", "/.well-known/security.txt says who to contact.")
    else:
        out.add("security_txt", "info", "No /.well-known/security.txt: consider adding one (securitytxt.org).")

    out.tables.append({
        "title": "Security checks", "columns": ["Check", "Result", "What was found", "Why it matters", "Standards"],
        "rows": [[f.title, "passed" if f.severity == "ok" else "advice" if f.severity == "info" else
                  f"failed ({f.severity})", f.detail, WHY[f.check], f.standards] for f in out.findings],
        "note": "Safe checks only: ordinary GET requests, nothing attack-like. SOC 2 and HIPAA are only mapped, "
                "not assessed."})
    if cookie_rows:
        out.tables.append({"title": f"{len(cookie_rows)} cookie(s) the site sets",
                           "columns": ["Cookie", "Set on", "Secure", "HttpOnly", "SameSite", "Problems"],
                           "rows": cookie_rows, "note": "HttpOnly is needed on login cookies; others may need "
                                                        "to be read by the page's own scripts."})
    if insecure:
        out.tables.append({"title": "Loaded or sent over plain http", "columns": ["Page", "Address", "What"],
                           "rows": insecure[:50], "note": ""})
    out.tables.append({"title": "Well-known private files", "columns": ["Address", "Result"], "rows": exposed_rows,
                       "note": "Contents are never shown or kept."})
    return out


def _headers(out: Results, h: dict[str, str], secure: bool) -> None:
    hsts = h.get("strict-transport-security", "")
    age = re.search(r"max-age=(\d+)", hsts)
    if not hsts:
        out.add("hsts", "medium", "missing HSTS (keeps browsers on HTTPS) header")
    elif not age or int(age.group(1)) < 15_552_000:
        out.add("hsts", "low", f"HSTS is set for less than six months ({hsts}); a year (31536000) is usual.")
    else:
        out.add("hsts", "ok", hsts)
    nosniff = h.get("x-content-type-options", "").lower()
    out.add("nosniff", "ok" if nosniff == "nosniff" else "low",
            "nosniff" if nosniff == "nosniff" else "missing X-Content-Type-Options: nosniff header")
    out.add("referrer", "ok" if "referrer-policy" in h else "low",
            h.get("referrer-policy", "missing Referrer-Policy header"))
    csp = h.get("content-security-policy", "")
    framed = "frame-ancestors" in csp or "x-frame-options" in h
    out.add("clickjacking", "ok" if framed else "medium",
            ("frame-ancestors" if "frame-ancestors" in csp else f"X-Frame-Options: {h.get('x-frame-options')}")
            if framed else "no clickjacking protection (Content-Security-Policy frame-ancestors or X-Frame-Options)")
    scripts = re.search(r"script-src[^;]*", csp) or re.search(r"default-src[^;]*", csp)
    if not csp:
        out.add("csp", "info", "No Content-Security-Policy: worth adding, starting in report-only mode.")
    elif scripts and "'unsafe-inline'" in scripts.group(0) and not re.search(r"'nonce-|'sha(256|384|512)-",
                                                                               scripts.group(0)):
        out.add("csp", "info", "The policy allows inline scripts ('unsafe-inline'), so it doesn't stop injected ones.")
    else:
        out.add("csp", "ok", csp[:150])
    out.add("permissions", "ok" if "permissions-policy" in h else "info",
            h.get("permissions-policy", "No Permissions-Policy header (optional).")[:150])
    leaks = [f"{name}: {h[name.lower()]}" for name in ("Server", "X-Powered-By", "X-AspNet-Version",
                                                       "X-AspNetMvc-Version")
             if name.lower() in h and (name != "Server" or VERSION.search(h["server"]))]
    out.add("versions", "low" if leaks else "ok",
            ("The site says which software versions it runs: " + "; ".join(leaks)) if leaks else
            "No software versions in the headers.")


def _cors(out: Results, request: Any, home: str, api: list[str]) -> None:
    worst, notes = "ok", []
    try:  # with no cookie held, "with the visitor's login" can't apply: the answer is public to anyone anyway
        has_login = bool(request.storage_state().get("cookies"))
    except Exception:  # noqa: BLE001
        has_login = True
    for url in [home, *api[:3]]:
        r = _get(request, url, headers={"Origin": TEST_ORIGIN})
        if r is None:
            continue
        h = {k.lower(): v for k, v in r.headers.items()}
        allow, creds = h.get("access-control-allow-origin", ""), h.get("access-control-allow-credentials", "")
        public = "/wp-json/" in url or not has_login
        if allow == TEST_ORIGIN and creds.lower() == "true" and public:
            level, note = "low", ("repeats any website's address back and allows logins; it is public data here "
                                  "(no login was needed), so nothing private is exposed, but allow only the sites "
                                  "that need it")
        elif allow == TEST_ORIGIN and creds.lower() == "true":
            level, note = "high", "lets any website read it with the visitor's login"
        elif allow == TEST_ORIGIN or allow == "null":
            level, note = "low", "lets any website read it (not with the visitor's login)"
        else:
            continue
        notes.append(f"{_path(url)} {note}")
        worst = max(worst, level, key=lambda s: -1 if s == "ok" else SEVERITIES.index(s))
    out.add("cors", worst, "; ".join(notes) if notes else
            f"{1 + min(len(api), 3)} address(es) checked with a request from another site: none lets it read them.")


def _path(url: str) -> str:
    p = urlparse(url)
    return p.path or "/"
