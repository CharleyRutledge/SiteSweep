"""Firefox that trusts what this computer trusts, for computers whose network re-signs HTTPS (Claude Code on the web).

Chrome and Safari's engine use the computer's list of trusted certificate authorities; Playwright's Firefox carries
its own, so behind such a network it refuses every HTTPS page. Certificate checking stays fully on: Firefox is
given a profile whose certificate store holds the computer's own list (SSL_CERT_FILE), nothing more.

Playwright only takes a ready-made Firefox profile with launch_persistent_context, which has one session. So
ProfileBrowser starts one Firefox per session, each with its own copy of the profile: roles, phones and tests stay
as separate from each other as with an ordinary browser. Used only when Firefox can't open the site otherwise.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

ENV = "WEB_UI_FIREFOX_PROFILE"  # set by the CLI when this Firefox is needed; the test run reads it
LAUNCHED: dict[str, str] = {}  # browser name -> version, for each browser this run started (the report shows them)


def certificate_bundle() -> str:
    """The computer's list of trusted certificate authorities, when it names one."""
    for name in ("SSL_CERT_FILE", "NODE_EXTRA_CA_CERTS", "REQUESTS_CA_BUNDLE"):
        path = os.environ.get(name, "")
        if path and Path(path).is_file():
            return path
    return ""


def build_profile() -> str:
    """A Firefox profile folder that trusts every authority in the computer's bundle; '' when that can't be made
    (no bundle, or no certutil: on Debian/Ubuntu it comes with libnss3-tools)."""
    bundle, certutil = certificate_bundle(), shutil.which("certutil")
    if not bundle or not certutil:
        return ""
    text = Path(bundle).read_text(encoding="utf-8", errors="replace")
    folder = Path(tempfile.gettempdir()) / f"sitesweep-firefox-{hashlib.sha256(text.encode()).hexdigest()[:16]}"
    if (folder / "ready").exists():
        return str(folder)
    shutil.rmtree(folder, ignore_errors=True)
    folder.mkdir(parents=True)
    db = f"sql:{folder}"
    try:
        subprocess.run([certutil, "-N", "--empty-password", "-d", db], check=True, capture_output=True)
        blocks = [b.strip() + "\n-----END CERTIFICATE-----\n" for b in text.split("-----END CERTIFICATE-----")
                  if "-----BEGIN CERTIFICATE-----" in b]
        for i, block in enumerate(blocks):
            pem = folder / "authority.pem"
            pem.write_text(block[block.index("-----BEGIN"):], encoding="utf-8")
            # C,, : trusted to issue website certificates, the same trust the computer gives it.
            subprocess.run([certutil, "-A", "-n", f"computer-authority-{i}", "-t", "C,,", "-i", str(pem), "-d", db],
                           check=True, capture_output=True)
        (folder / "authority.pem").unlink(missing_ok=True)
    except (OSError, subprocess.CalledProcessError):
        shutil.rmtree(folder, ignore_errors=True)
        return ""
    (folder / "ready").write_text("", encoding="utf-8")
    return str(folder)


def _storage_script(state: dict) -> str:
    """Puts a storage state's localStorage back, once per origin and tab, as storage_state= would."""
    origins = json.dumps(state.get("origins") or [])
    return f"""(() => {{
      const o = {origins}.find(x => x.origin === location.origin);
      if (!o || sessionStorage.getItem('__sitesweep_state')) return;
      for (const item of o.localStorage || []) localStorage.setItem(item.name, item.value);
      sessionStorage.setItem('__sitesweep_state', '1');
    }})();"""


class ProfileBrowser:
    """Looks like a Playwright Browser to SiteSweep and pytest-playwright: new_context() gives a separate Firefox
    with its own copy of the trusted profile."""

    def __init__(self, browser_type: Any, launch_options: dict, template: str) -> None:
        self.browser_type = browser_type
        self._options = launch_options
        self._template = template
        self._contexts: list[Any] = []

    @property
    def contexts(self) -> list[Any]:
        return list(self._contexts)

    @property
    def version(self) -> str:
        return ""

    def is_connected(self) -> bool:
        return True

    def new_context(self, **kwargs: Any) -> Any:
        state = kwargs.pop("storage_state", None)
        folder = tempfile.mkdtemp(prefix="sitesweep-firefox-session-")
        shutil.copytree(self._template, folder, dirs_exist_ok=True, ignore=shutil.ignore_patterns("ready"))
        context = self.browser_type.launch_persistent_context(folder, **self._options, **kwargs)
        # The persistent browser opens a blank tab of its own (closing it would end the browser): the first
        # new_page() gets that tab, so a session has only the tabs it asked for.
        spare = list(context.pages)
        original_new_page = context.new_page

        def new_page(*args: Any, **kw: Any) -> Any:
            return spare.pop() if spare and not args and not kw else original_new_page(*args, **kw)

        context.new_page = new_page
        if state:
            data = json.loads(Path(state).read_text(encoding="utf-8")) if isinstance(state, (str, Path)) else state
            if data.get("cookies"):
                context.add_cookies(data["cookies"])
            if data.get("origins"):
                context.add_init_script(_storage_script(data))
        original_close = context.close

        def close(*args: Any, **kw: Any) -> None:
            if context in self._contexts:
                self._contexts.remove(context)
            try:
                original_close(*args, **kw)
            finally:
                shutil.rmtree(folder, ignore_errors=True)

        context.close = close
        self._contexts.append(context)
        return context

    def new_page(self, **kwargs: Any) -> Any:
        return self.new_context(**kwargs).new_page()

    def close(self) -> None:
        for context in self.contexts:
            context.close()


def launch(browser_type: Any, **launch_options: Any) -> Any:
    """browser_type.launch(), or the trusted-profile Firefox when the CLI chose it for this run."""
    template = os.environ.get(ENV, "")
    if browser_type.name == "firefox" and template and Path(template).is_dir():
        browser = ProfileBrowser(browser_type, launch_options, template)
    else:
        browser = browser_type.launch(**launch_options)
        LAUNCHED[browser_type.name] = browser.version
    return browser
