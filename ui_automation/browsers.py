"""Making sure every browser a run needs is installed (Chromium, Firefox, WebKit), installing what is missing."""

from __future__ import annotations

import os
import re
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path

# A Chromium that comes with the computer (Claude Code on the web has one here). Used only when Playwright's own
# build can't be downloaded, e.g. when the network allows the site under test but not Playwright's download server.
PREINSTALLED_CHROMIUM = [Path("/opt/pw-browsers/chromium")]
# Where Playwright downloads its browsers from.
DOWNLOAD_HOSTS = ("cdn.playwright.dev", "playwright.download.prss.microsoft.com")


def preinstalled_chromium() -> str:
    """WEB_UI_CHROMIUM if it names a browser that exists, else a Chromium that came with the computer, else ''."""
    for path in [Path(p) for p in [os.environ.get("WEB_UI_CHROMIUM", "")] if p] + PREINSTALLED_CHROMIUM:
        if path.is_file():
            return str(path)
    return ""


def proxy_settings() -> dict[str, str] | None:
    """The computer's HTTPS proxy (HTTPS_PROXY / NO_PROXY), for Playwright. Browsers find it on their own, but the
    requests Playwright makes outside the page (link checks, the HTTPS check, API replays) only use it when told."""
    server = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy") or ""
    if not server:
        return None
    raw = os.environ.get("NO_PROXY") or os.environ.get("no_proxy") or ""
    # Host names and plain addresses only: every browser understands those. This computer always goes direct.
    names = ["localhost", "127.0.0.1"] + [h.strip() for h in raw.split(",")
                                          if re.fullmatch(r"\.?[A-Za-z0-9.-]+", h.strip() or "-")]
    return {"server": server, "bypass": ",".join(dict.fromkeys(names))}


def launch_options(name: str) -> dict:
    """Extra launch options for browser `name`: the computer's proxy, and the stand-in Chromium when
    ensure_browsers chose one."""
    options: dict = {}
    path = os.environ.get("WEB_UI_CHROMIUM", "")
    if name == "chromium" and path:
        options["executable_path"] = path
    proxy = proxy_settings()
    if proxy:
        options["proxy"] = proxy
    return options


def missing_browsers(names: list[str]) -> list[str]:
    """The browsers in `names` whose Playwright build is not on this computer."""
    from playwright.sync_api import Error as PlaywrightError, sync_playwright

    missing: list[str] = []
    try:
        with sync_playwright() as p:
            for name in names:
                try:
                    if Path(getattr(p, name).executable_path).exists():
                        continue
                    # Not where expected: headless runs can use a separate build, so try starting it.
                    getattr(p, name).launch(headless=True).close()
                except PlaywrightError as exc:
                    if "Executable doesn't exist" in str(exc) or "playwright install" in str(exc):
                        missing.append(name)
                except AttributeError:
                    missing.append(name)
    except PlaywrightError:
        return []  # Playwright itself cannot start: the run reports that clearly on its own
    return missing


def ensure_browsers(names: list[str]) -> str:
    """Install the missing ones with Playwright's own installer. '' when all are there, else what went wrong."""
    missing = missing_browsers(list(dict.fromkeys(names)))
    if not missing:
        return ""
    print(f"Installing {', '.join(missing)} for this run (a one-time download) ...", flush=True)
    done = subprocess.run([sys.executable, "-m", "playwright", "install", *missing], check=False)
    if done.returncode == 0:
        return ""
    stand_in = preinstalled_chromium() if "chromium" in missing else ""
    if stand_in:
        os.environ["WEB_UI_CHROMIUM"] = stand_in  # read again by the test run (conftest.py, site audit)
        print(f"Using the Chromium already on this computer instead: {stand_in}", flush=True)
        missing = [m for m in missing if m != "chromium"]
        if not missing:
            return ""
    return (f"Could not install {', '.join(missing)}. Run: python -m playwright install {' '.join(missing)}"
            + (" (on Linux add --with-deps)" if sys.platform.startswith("linux") else "")
            + (". In Claude Code on the web, the environment's network access must allow "
               f"{' and '.join(DOWNLOAD_HOSTS)}" if os.environ.get("CLAUDE_CODE_REMOTE") == "true" else ""))


# The proxy re-signs HTTPS with its own certificate, which a browser with its own certificate store may not trust.
_CERT_ERRORS = ("SEC_ERROR_UNKNOWN_ISSUER", "ERR_CERT_AUTHORITY_INVALID", "unable to get local issuer",
                "self signed certificate in certificate chain", "SSL peer certificate or SSH remote key was not OK")
_NAMES = {"chromium": "Chrome's engine (Chromium)", "firefox": "Firefox", "webkit": "Safari's engine (WebKit)"}


def _try(name: str, url: str) -> str:
    """'' when `name` starts and, behind a proxy, can open the https site; else the error."""
    from playwright.sync_api import Error as PlaywrightError, sync_playwright

    from ui_automation.local import is_local  # local addresses never go through the proxy

    with sync_playwright() as p:
        try:
            browser = getattr(p, name).launch(headless=True, **launch_options(name))
        except PlaywrightError as exc:
            return str(exc)
        try:
            if proxy_settings() and url.lower().startswith("https://") and not is_local(url):
                browser.new_page().goto(url, wait_until="commit", timeout=20_000)
        except PlaywrightError as exc:
            message = str(exc)
            return message if any(e in message for e in _CERT_ERRORS) else ""  # anything else is the site's to report
        finally:
            browser.close()
    return ""


def usable_browsers(names: list[str], url: str) -> tuple[list[str], list[str]]:
    """The browsers in `names` that can test `url` on this computer, and why each other one can't.
    Missing system libraries are installed when allowed (Linux, as root); nothing else is changed."""
    usable: list[str] = []
    why_not: list[str] = []
    for name in dict.fromkeys(names):
        problem = _try(name, url)
        if "missing dependencies" in problem and sys.platform.startswith("linux") and os.geteuid() == 0:
            print(f"Installing the system libraries {_NAMES.get(name, name)} needs ...", flush=True)
            subprocess.run([sys.executable, "-m", "playwright", "install-deps", name], check=False)
            problem = _try(name, url)
        label = _NAMES.get(name, name)
        if not problem:
            usable.append(name)
        elif "missing dependencies" in problem:
            why_not.append(f"{label}: this computer is missing system libraries it needs "
                           f"(run: sudo python -m playwright install-deps {name})")
        elif any(e in problem for e in _CERT_ERRORS):
            why_not.append(f"{label}: it doesn't trust the certificate of this computer's network proxy, so it can't "
                           "open HTTPS sites here (it works on a computer without that proxy, e.g. your own)")
        else:
            first = problem.strip().splitlines()[0].replace("BrowserType.launch: ", "")
            why_not.append(f"{label}: could not start ({first[:300]})")
    return usable, why_not


def irish_today() -> date:
    try:
        from zoneinfo import ZoneInfo

        return datetime.now(ZoneInfo("Europe/Dublin")).date()
    except Exception:  # noqa: BLE001 - no time zone data (some Windows installs): the computer's date
        return date.today()


def browsers_for_run(browsers: tuple[str, ...] | list[str], rotation: str, today: date | None = None) -> list[str]:
    """The browsers (or mobile devices) this run uses. With browser_rotation: daily, one of them, taking turns
    by the day, unless WEB_UI_ALL_BROWSERS=1 (the --all-browsers option) asks for all of them."""
    names = list(browsers)
    if rotation != "daily" or len(names) < 2 or os.environ.get("WEB_UI_ALL_BROWSERS") == "1":
        return names
    day = today or irish_today()
    return [names[day.toordinal() % len(names)]]


def device_engines(devices: list[str]) -> list[str]:
    """The browser each mobile device runs in (iPhone: webkit, Pixel: chromium), for installing them first."""
    from playwright.sync_api import Error as PlaywrightError, sync_playwright

    if not devices:
        return []
    try:
        with sync_playwright() as p:
            return list(dict.fromkeys(p.devices[d]["default_browser_type"] for d in devices if d in p.devices))
    except PlaywrightError:
        return []
