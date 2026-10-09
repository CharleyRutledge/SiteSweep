"""Before testing from Claude Code on the web: can this session reach the site, everything its pages load, and the
browser download servers? Its network only reaches the domains the environment allows, so this lists exactly
which ones to add, ready to copy.

    python -m ui_automation.reach https://www.example.ie
    python -m ui_automation.reach --config config/site-audit.yaml

Exit codes: 0 nothing to change, 3 the address is on the person's own computer (a cloud session can't reach it),
4 domains to allow (listed), 2 bad input.
"""

from __future__ import annotations

import argparse
import os
import sys
import urllib.error
import urllib.request
from urllib.parse import urlparse

from ui_automation.browsers import DOWNLOAD_HOSTS, launch_options, missing_browsers
from ui_automation.local import is_local

DOCS = "https://code.claude.com/docs/en/cloud-environments#network-access"
HOW = ("How: click the environment's name in this session's title bar -> Edit -> Network access -> Limited\n"
       "(called Custom in older apps). Keep \"Allow package managers\" ticked, add the domains above under Allowed\n"
       "domains, and save. On a phone, the same menu is in the session at claude.ai/code in the browser.\n"
       f"Then say \"done\" and I'll check again. Steps: {DOCS}")
ON_YOUR_COMPUTER = """\
{url} is on your own computer, and this session runs in the cloud: it can't reach your computer.

Test it from a Claude session that runs on your computer instead (the app must be running there):
  - Claude Desktop app: open the Code tab, choose your SiteSweep folder, and type /test
  - Or in a terminal in your SiteSweep folder, run:  claude remote-control
    then open that session in the Claude app (phone or web) and type /test. It runs on your computer."""


def in_the_cloud() -> bool:
    return os.environ.get("CLAUDE_CODE_REMOTE") == "true"


def is_blocked(host: str, timeout: float = 15.0) -> bool:
    """True when the session's network refuses `host` (its proxy answers 403 to the connection), not when the
    site itself is down or answers with an error page."""
    opener = urllib.request.build_opener(urllib.request.ProxyHandler())  # the proxy settings of this moment
    request = urllib.request.Request(f"https://{host}/", method="HEAD", headers={"User-Agent": "sitesweep-reach"})
    try:
        # Always https:// to a host name.
        with opener.open(request, timeout=timeout):  # nosec B310
            return False
    except urllib.error.HTTPError:
        return False  # the site answered
    except (urllib.error.URLError, OSError) as exc:
        return "Tunnel connection failed: 403" in str(getattr(exc, "reason", exc))


def hosts_the_page_needs(url: str, proxy: dict | None = None, timeout_ms: int = 20_000) -> list[str]:
    """Domains the page at `url` tried to load from (scripts, APIs, fonts, images) but couldn't connect to."""
    from playwright.sync_api import Error as PlaywrightError, sync_playwright

    failed: set[str] = set()
    with sync_playwright() as p:
        options = launch_options("chromium")
        if proxy:
            options["proxy"] = proxy
        browser = p.chromium.launch(headless=True, **options)
        try:
            page = browser.new_page(ignore_https_errors=True)
            page.on("requestfailed", lambda r: failed.add(urlparse(r.url).hostname or "")
                    if "TUNNEL_CONNECTION_FAILED" in (r.failure or "") or "PROXY" in (r.failure or "") else None)
            try:
                page.goto(url, wait_until="load", timeout=timeout_ms)
                page.wait_for_timeout(1500)  # requests the page makes once it has loaded
            except PlaywrightError:
                pass  # the failed requests say why
        finally:
            browser.close()
    return sorted(h for h in failed if h)


def domains_to_allow(url: str) -> list[str]:
    """What this cloud session needs allowed to test `url`, in the order to add them."""
    host = urlparse(url).hostname or ""
    needed: list[str] = []
    if is_blocked(host):
        needed.append(host)
    else:
        needed += [h for h in hosts_the_page_needs(url) if h != host and is_blocked(h)]
    if missing_browsers(["chromium", "firefox", "webkit"]):
        needed += [h for h in DOWNLOAD_HOSTS if is_blocked(h)]
    return list(dict.fromkeys(needed))


def report(url: str) -> tuple[int, str]:
    if not in_the_cloud():
        return 0, f"This runs on your own computer: it can reach {url} directly, nothing to set up."
    if is_local(url):
        return 3, ON_YOUR_COMPUTER.format(url=url)
    needed = domains_to_allow(url)
    if not needed:
        return 0, f"This session can reach {url}, everything its home page loads, and the browser downloads."
    lines = "\n".join(f"    {d}" for d in needed)
    return 4, f"To test {url} from the cloud, allow these domains:\n\n{lines}\n\n{HOW}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m ui_automation.reach", description=__doc__.split("\n\n")[0])
    parser.add_argument("url", nargs="?", help="The website, e.g. https://www.example.ie")
    parser.add_argument("--config", help="Or a settings file: its base_url is checked")
    args = parser.parse_args(argv)
    url = args.url
    if not url and args.config:
        from ui_automation.config import load_settings

        url = load_settings(args.config).base_url
    if not url or not url.lower().startswith(("http://", "https://")):
        print("Give the website's address, starting with http:// or https://", file=sys.stderr)
        return 2
    code, message = report(url)
    print(message)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
