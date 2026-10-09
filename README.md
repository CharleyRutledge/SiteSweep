# SiteSweep

**Point it at any website or web app and it checks every page:** broken links and images, errors, slow pages,
accessibility (WCAG 2.1 AA / EN 301 549, with a copyable fix for each issue), Irish/EU website requirements,
GDPR and cookies, security (safe checks only), languages and translations, phones and every screen size,
Chrome, Firefox and Safari's engine (with a compatibility grid), the app's API, and what each kind of
logged-in user can and can't see. It also tests **MCP servers**, and can watch a site or MCP server every hour
for uptime, MTBF and MTTR. You get a plain-language report, on your computer, by Telegram or by email.

Created by [Charley Rutledge](https://github.com/CharleyRutledge). Built with Python, [Playwright](https://playwright.dev)
and pytest, with optional summaries by Claude.

[![License: Apache 2.0](https://img.shields.io/badge/License-Apache%202.0-blue?style=flat-square)](LICENSE)
[![Buy Me A Coffee](https://img.shields.io/badge/Buy%20Me%20A%20Coffee-support-FFDD00?style=flat-square&logo=buy-me-a-coffee&logoColor=black)](https://buymeacoffee.com/charleyrutledge)

## Open in Claude

[![1. Fork on GitHub](https://img.shields.io/badge/1.%20Fork-on%20GitHub-24292F?style=for-the-badge&logo=github&logoColor=white)](https://github.com/CharleyRutledge/SiteSweep/fork)
[![2. Open in Claude (fork first)](https://img.shields.io/badge/2.%20Open%20in%20Claude-fork%20first-D97757?style=for-the-badge&logo=claude&logoColor=white)](https://claude.ai/code?repositories=CharleyRutledge/SiteSweep&prompt=%2Ftest)

**Using SiteSweep for the first time?** Tap **1. Fork** to make your own copy, then start a session with your
fork (see "First time" below). **2. Open in Claude** opens this repository itself, which only its owner can
do; on a computer it fills in the repository and `/test` for you.

Once a session is open with SiteSweep, Claude asks what to test and how thorough. It then
runs the site audit and explains the report. In the same session you can also type:

| Command | What it does |
|---------|--------------|
| `/test` | Test a website or app: asks what, how thorough, which kinds of testing and which legal checks ([steps](.claude/skills/test/SKILL.md)) |
| `/test-mcp` | Test an MCP server by its address or as a local command ([steps](.claude/skills/test-mcp/SKILL.md)) |
| `/reliability` | Watch a site or MCP server every hour: your own private page with uptime, MTBF and MTTR ([steps](.claude/skills/reliability/SKILL.md)) |

**First time: make your own copy (fork).** Claude can only open repositories connected to your own GitHub
account, so other people's repositories, this one included, aren't in your list. On GitHub, tap **Fork** at the
top of this page (it's free and the licence allows it). Then start a session at claude.ai/code (or in the
Claude app), tap **Add repository**, pick your fork, and type `/test`. Your own settings never go into your fork
either: `config/private/` and `.env` are never committed. To get new versions later, tap **Sync fork** on GitHub.

**A website (in the cloud, the button).** Before testing, `/test` checks what the session's network can reach
(`python -m ui_automation.reach <address>`). If something is refused, it lists the exact domains to allow,
ready to copy: the site, any other sites its pages load from, and the browser download servers. You paste them
once: the environment's name in the session's title bar -> **Edit** -> **Network access** -> **Limited** (called
**Custom** in older apps) -> **Allowed domains**, with **Allow package managers** left ticked
([steps](https://code.claude.com/docs/en/cloud-environments#network-access)). This works from the phone app too;
if it doesn't show the menu, open the session at claude.ai/code in the phone's browser. Then say "done" and it
checks again and runs.

**Logins (tokens and passwords)** are never typed into the chat or stored in the repository. On your computer
they go in `.env`; in a cloud session, add them in the same **Edit** screen under **Network secrets** (or as an
environment variable). A new session picks them up.

**An app on your computer (`localhost`).** A cloud session can't reach your computer, so run `/test` in a Claude
session that runs on your computer. Start the app first, then either:

- **Claude Desktop app:** open the **Code** tab, choose your SiteSweep folder, and type `/test`.
- **From your phone or the web (Remote Control):** in a terminal in your SiteSweep folder run
  `claude remote-control`, then open that session in the Claude app and type `/test`. It runs on your computer.
- **In a terminal:** run `claude /test` in your SiteSweep folder.

In each case `/test` pulls the latest code and updates the packages. It then offers your own settings files in
`config/private/` (logins come from `.env`), and every browser installs itself the first time. The report opens on
your computer, and is sent to the chat too when you follow along from another device.

## Quick start (without Claude)

```powershell
git clone https://github.com/CharleyRutledge/SiteSweep.git
cd SiteSweep
python -m pip install -r requirements.txt
python -m ui_automation --config config/site-audit.yaml --url https://example.ie --open -- site_audit
```

The browsers it needs install themselves on the first run, and `--open` opens the report when it finishes.

## Open the report

| Path | Contents |
|------|----------|
| `reports/<timestamp>/summary.html` | The plain-language report: what each check means, what it found (evidence tables), fixes, the compatibility grid, website requirements and GDPR |
| `reports/<timestamp>/summary.json` | The same results as data (also lists what was not run and why) |
| `reports/<timestamp>/report.html` | The detailed report ("SiteSweep detailed report", pytest-html), with embedded step screenshots; corrected after each run to meet WCAG 2.2 AA |
| `reports/latest/report.html` | Copy of the last run |
| `reports/<timestamp>/summary.html` (on a phone) | Fits a 320px screen; it is what Telegram and email send, with videos, screenshots and traces embedded |
| `reports/<timestamp>/videos/` | Recordings per browser test: `.webm`, plus `.mp4` when `ffmpeg` is installed (plays on iPhone) |
| `reports/<timestamp>/screenshots/` | A screenshot per test step |
| `reports/<timestamp>/failure-screenshots/` | Playwright's screenshot at the moment a test failed |
| `reports/<timestamp>/traces/` | Playwright trace `.zip` on failure (open at [trace.playwright.dev](https://trace.playwright.dev)) |
| `reports/<timestamp>/claude_summary.txt` | AI analysis (when enabled) |

```powershell
Invoke-Item .\reports\latest\report.html
```

## Accessibility and website requirements

**Accessibility** (`accessibility:` in `config/settings.yaml`, on by default): every page in `pages` is
scanned in the real browser with [axe-core](https://github.com/dequelabs/axe-core) 4.13 (vendored, checksum
verified). The default standard is **WCAG 2.1 AA**, the level EN 301 549 requires under the EU Web
Accessibility Directive (S.I. 358/2020) and the European Accessibility Act; `wcag22aa` adds the WCAG 2.2
criteria. Each issue is reported with its WCAG success criterion, the failing elements and, for each one, the corrected code (markup or CSS) with a Copy button, and the test fails
at `fail_on` severity (`none` = report only). Automated rules cannot prove conformance: the report lists what
still needs a person to check, following the W3C WCAG-EM method (scope, explore, sample, audit, report).
The report and dashboard themselves are tested against WCAG 2.2 AA (axe, keyboard, focus, 320 px reflow).

**Website requirements (Ireland / EU)** (`compliance:`, always on; `report_only: true` lists problems
without failing the run, for sites that aren't yours): checks each page, before any
consent is given, for a privacy notice link (GDPR Art. 13/14), no tracking cookies or tracker requests
before consent and a reject option (ePrivacy Regulations S.I. 336/2011, DPC guidance), an accessibility
statement link, company details (Companies Act 2014 s.151, S.I. 68/2003), contact details and terms.
Trackers are blocked during the check, so tests never send analytics. These checks find what is missing or
misbehaving; the wording of policies still needs review (and legal advice).

**GDPR and cookies** (`compliance.gdpr`, on with `compliance:`), done the way the EDPB's website auditing
tool does it: the site is opened three times in a fresh browser (no choice made, after "Reject", after
"Accept"), on the home page and the pages most likely to ask for personal data (`compliance.gdpr_pages`,
3 by default), and every cookie (who sets it, how long it lasts), stored item and other site contacted is
recorded each time. Then it checks:

- nothing that tracks people before a choice, and nothing sent to companies outside the EU before it
  (ePrivacy Regulations 2011 Reg. 5(3); GDPR Chapter V)
- "Reject" on the first screen, as easy to see as "Accept" (DPC guidance; EDPB cookie banner taskforce)
- no boxes ticked in advance (GDPR Art. 4(11) and 7; CJEU Planet49)
- "Reject" really stops tracking, and a way to change the choice stays on the page (GDPR Art. 7(3))
- the privacy notice covers what GDPR Art. 13 lists (controller, DPO, purposes, legal basis, recipients,
  transfers, retention, rights, withdrawing consent, complaining to the Data Protection Commission)
- forms that ask for personal data are sent over HTTPS, link the privacy notice and have no marketing box
  ticked in advance

The report shows each result with its law, and tables of the cookies, other sites and notice items found.
Only the banner's own buttons are pressed, forms are never submitted, and tracker requests are blocked.
These checks find clear problems; they can't prove a site complies with GDPR.

**Security, safe checks only** (`audit.security_checks`; `auto` leaves them for the deployed site). Done with
ordinary GET requests anyone's browser makes, never anything attack-like: no logins tried, no forms sent, no
injected input, no port scanning. It checks:

- HTTPS, http:// sent on to it, and the certificate (trusted, not about to expire)
- the security headers: HSTS, nosniff, Referrer-Policy, clickjacking protection; a Content Security Policy
  and Permissions-Policy are suggested
- software versions given away in headers (`Server: Apache/2.4.41`, `X-Powered-By`)
- cookies the site sets: Secure, HttpOnly on login cookies, SameSite
- files or forms on HTTPS pages that use plain http
- 7 well-known files that must never be public (`.git`, `.env`, `.htpasswd`, a `wp-config.php` backup,
  server status, `phpinfo`, `.DS_Store`), recognised by their contents, so a "not found" page that answers
  200 never counts. If one is found, the report gives its size, never its contents
- folders of the site's own files that list everything in them
- CORS: whether another website may read the site's data, with or without the visitor's login
- `/.well-known/security.txt` (suggested)

Each result names the standard it comes from: OWASP ASVS 4.0.3 and Top 10 (2021). SOC 2 and HIPAA controls
are mapped (the control a result is evidence for), not assessed: that needs an auditor.

**Languages and translations**, on up to 5 pages and every language version of the home page:

- each page says which language it is in (WCAG 3.1.1), with a valid code, and its text really is in that
  language (recognised from its most common short words, for English, Irish, French, German, Spanish,
  Italian, Dutch, Portuguese and Polish)
- no translation keys (`checkout.button.submit`), `{{placeholders}}` or "translation missing" showing, and
  no garbled characters (`CafÃ©`)
- right-to-left languages (Arabic, Hebrew...) set to `dir="rtl"`
- for a site in several languages: every version listed with `hreflang` opens, says the right language, is
  really translated, links back, fits a 375px phone screen, and a language switcher is on the page

This finds what is missing or left untranslated; it doesn't judge the quality of a translation.

**Compatibility.** The report's Compatibility section is a grid of every check in every browser (Chrome's
engine, Firefox, Safari's engine) with the operating system and browser versions used, and a table of the
phones checked. Browsers run on the computer doing the test, so to cover another operating system, run
SiteSweep there too (for a Mac, the Claude Desktop app) and combine the runs into one grid:

    python -m ui_automation.reporting.compat reports/<run> reports/<run from the Mac> -o compatibility.html

**Reliability: uptime, MTBF and MTTR.** Type `/reliability` in Claude. It asks which pages to watch, then
sets up a private claude.ai page and an hourly Claude Routine on your own account. Each hour the Routine checks
the pages (`python -m ui_automation.reliability check <addresses>`) and adds the result to your page. The page
shows uptime, every outage (when it went down, when it came back, why), MTBF (time between failures) and MTTR
(time to recover). The history belongs to the person who set it up: it is never stored in this repository,
and the page's data can only be read by its owner, even if the page is shared. An hour when the checking
network couldn't reach the site counts as "not checked", never as down.

## Test an MCP server

The same kinds of checks for a Model Context Protocol server, safe checks only (type `/test-mcp` in Claude):

    python -m ui_automation.mcp_audit https://example.ie/mcp [--token-env NAME]
    python -m ui_automation.mcp_audit --command "npx -y @example/mcp-server"
    python -m ui_automation.mcp_audit --config config/private/mcp.yaml   # see config/mcp.example.yaml

- **Handshake and lists:** `initialize`, `ping`, the standard error for an unknown request, and every tool,
  resource and prompt listed (all pages), each tool with a usable name, a description and an input schema
- **Speed:** the handshake and the tool list against `budget_ms`
- **Security:** HTTPS, refusing requests from other websites (`Origin`, which the spec requires against DNS
  rebinding), CORS, refusing callers without a login and publishing where to log in (OAuth protected resource
  metadata, RFC 9728), and no software versions or stack traces given away
- **Tool safety:** instructions hidden in tool descriptions that speak to the AI ("tool poisoning": ignore your
  instructions, don't tell the user, read `~/.ssh`, send data elsewhere, invisible characters), and tools that
  change things without saying so (`destructiveHint`)
- **Logins:** each login (a token from an environment variable) sees the tools it should and none it shouldn't
- **Compatibility:** streamable HTTP, the older HTTP+SSE connection, local commands (stdio), and protocol
  versions 2025-06-18, 2025-03-26 and 2024-11-05
- **Read-only tools:** only the tools you list under `call_readonly`, with your inputs, and only if the server
  marks them read-only, are called; nothing that changes data is ever called

Uptime, MTBF and MTTR work the same way as for websites: `/reliability`, where an MCP server counts as up only
when it completes the handshake (`python -m ui_automation.reliability check --mcp <address>`).

## Audit any website

`site_audit/` audits a whole site from its `base_url`. It finds the pages by following the site's own links,
home page first, up to `audit.max_pages`. Every page found is then checked for:

- loading, with a title and a main heading
- uncaught JavaScript errors
- network errors: every request the page makes (scripts, styles, images, fonts, API calls) that fails or
  gets HTTP 400 or above
- broken links (internal, plus up to 60 external) and broken images
- sideways scrolling at every screen size in `audit.screens` (by default a 320 px small phone for WCAG
  1.4.10, a phone, a tablet, a laptop and a desktop), with a screenshot at each size that breaks
- real phones (`audit.mobile_devices`, by default an iPhone 15 in Safari's engine and a Pixel 7 in Chrome):
  each page opened with the phone's screen, touch and mobile browser, as each role, and checked for a
  viewport tag, sideways scrolling, text under 12px, buttons too small to tap (axe's WCAG 2.5.8 rule) and
  errors; the phones take turns by day like the browsers
- the app's API: every API call the pages make (fetch / XHR) must answer without an error and within
  `audit.api_budget_ms`; each logged-in role's read requests are sent again with no login and as every
  other role, so data handed out without logging in, or to the wrong role, is reported. Only GET requests
  are replayed (nothing that changes data), and tokens never reach a report. Endpoints meant to be
  public go in `audit.public_api`
- load time against `audit.load_budget_ms`
- security, with safe checks only (see below)
- languages and translations (see below)
- a WCAG scan, with a copyable fix for each issue: axe-core's rules, plus what axe cannot check alone,
  done the way a person uses the page: Tab through it (focus never stuck, always visible, nothing
  mouse-only), larger text spacing (no text cut off), alt text that says nothing, videos without
  captions, automatic refresh, endless animation with no pause, and skipped heading levels. The report
  lists what is checked automatically and what still needs a person
- Irish/EU website requirements on the home page
- GDPR and cookies (see above)

Pages built in the browser (React, Vue, ...) are measured only once they show real content: the audit waits
until the page has visible text with no "Loading..." or spinner, and has stopped changing (up to
`audit.content_wait_ms`, 15 s by default). A page that never gets there is reported as still loading, not
as a page with no heading.

Each page is opened once and all of this is measured on that visit, so a 25-page audit stays quick.
Each check lists every problem it finds, not just the first.

**Several browsers, for any app.** By default every page is checked in Chrome's engine, Firefox and WebKit
(the engine Safari uses), set with `browsers: [chromium, firefox, webkit]` (or `browser: chromium` for
one only); a missing browser is installed automatically before the run.
Checks that do not depend on the browser (links, HTTPS, legal pages) run once. The report's buttons
filter by browser and role. Each run uses one of them, taking turns by day (`browser_rotation: daily`,
the default), so runs stay quick; `--all-browsers` runs every one (e.g. before a release), and
`browser_rotation: off` always runs all of them.

**Nothing is skipped.** A check that does not apply to the run (HTTPS on a local app, a site-wide check
again for each role, permission checks for a role with no restricted pages listed) is not run at all, and
the end of the run lists each one with the reason, so you can see exactly what was not covered.

```bash
python -m ui_automation --config config/site-audit.yaml --url https://example.ie -- site_audit
```

`--url` works with any settings file and names the report after that site. In GitHub, go to
**Actions → Site audit → Run workflow** and type the website's address. Problems found on the site show
as a warning on a green run (the report is the result); the run fails only when the audit itself
could not run.

**Nothing runs on its own.** No suite is scheduled, and none that visits a website or sends a report
runs on push. The site audit, the practice sites, the browser suite and the load and live
checks only run when you start them in **Actions** (the site audit only with the URL you type). The
self-tests and security scan still run on every push and pull request; they use local test servers and
send nothing.

## Test behind a login, with roles

The site audit can log in and test as several kinds of user. It runs once logged out and once per role,
and the report labels every check with its role (e.g. `admin · chromium`).

```yaml
auth:
  login_url: /login
  roles:
    - name: admin
      username: "${APP_ADMIN_USER}"
      password: "${APP_ADMIN_PASSWORD}"
      start: /dashboard
    - name: viewer
      username: "${APP_VIEWER_USER}"
      password: "${APP_VIEWER_PASSWORD}"
      must_not_access: [/admin]   # checked: this role must be refused these pages
      pages: [/settings]          # optional: pages no link leads to, checked as well
      # area: /app                # optional: keep this role's crawl to pages under /app
```

- **Each role checks its own pages.** Pages the logged-out visitor already checked (and could really open)
  are not opened again by the roles, so each role's page budget (`audit.max_pages`) goes to the signed-in
  part of the app. The report lists every page each role checked.

- **Credentials** come from environment variables or the git-ignored `.env`, never from the settings file.
  A missing one is named in the error.
- **The login form** is found automatically (email or username box, password box, log-in button),
  including two-step logins where the password comes on a second screen. Set `username_field`,
  `password_field`, `submit` or `logged_in_check` if your form needs them.
- **No recording of the login.** It runs in a browser session with no video, trace or screenshot. Only the
  session it creates is used by the audit, so a password cannot end up in a report.
- **Safe crawling.** Log-out, delete and similar links are never followed or requested, so roles stay
  logged in and no data is changed.
- **Site-wide checks** (HTTPS, website requirements) run once, not again for every role.

## Test an app on your own computer (localhost)

Apps on your computer or local network (`localhost`, `127.0.0.1`, `192.168.x.x`, `*.local`) are tested
from **your computer**: GitHub's machines cannot reach them.

Keep the settings file for your own app in `config/private/` (for example `config/private/my-app.yaml`, copied
from `config/site-audit.yaml`). That folder is git-ignored, so private apps' addresses, page lists and role names
never reach GitHub. `/test` offers the files in it on your computer.

```bash
# The app is already running:
python -m ui_automation --config config/private/my-app.yaml -- site_audit
# Another port:
python -m ui_automation --config config/private/my-app.yaml --url http://localhost:5173 -- site_audit
# Let the tests start the app, wait until it answers, and stop it afterwards:
python -m ui_automation --config config/private/my-app.yaml --start "npm run dev" --start-in ../my-app -- site_audit
```

- Apps in **Docker**: a start command that runs in the background (`docker compose up -d --wait`) is
  fine. Give it a stop command (`--stop "docker compose down"`) to shut the app down after the tests.
- Save the commands in the settings file instead of typing them each time:
  ```yaml
  app:
    start: "docker compose up -d --wait"
    stop: "docker compose down"
    start_in: "C:/Users/me/my-app"
  ```
  If the app is already running, it is tested as it is and left running. `--no-start` never starts it.
- If nothing is answering at the address, the app says so and stops. It runs no tests and creates no
  empty report.
- With `--start`, the app's own output is saved as `app-server.log` in the run folder. If the app fails
  to start, or doesn't answer within `--start-timeout` (120 s), the run stops and the app is shut down.
- Self-signed HTTPS certificates are accepted for local addresses only. The HTTPS and security-header
  checks are left for the deployed site (`audit.security_checks: on` runs them locally too).
- For Telegram reports from your computer, copy `.env.example` to `.env` and fill in your keys. `.env`
  is git-ignored and never leaves your computer; GitHub runs use the repository secrets.

## Package updates

`.github/dependabot.yml` keeps every package up to date: each Monday GitHub checks the Python packages and
the GitHub Actions, and opens **one** pull request with all available updates. The self-tests run on it;
it is merged by hand like any other change. On your computer, `git pull` and then
`python -m pip install -U -r requirements.txt` brings the new versions in.

## Testing the framework itself

The framework has its own test suite in `selftests/` (separate from the UI tests in `tests/`). Every test
talks to real local servers over real sockets: a scenario website, SMTP servers (plain, STARTTLS, implicit
TLS, login), and local stand-ins for the Telegram and Anthropic APIs, used for the error paths
(401/429/500, timeouts, broken replies) the real services cannot produce on demand.

While working on one feature, run just its tests (much quicker), e.g.
`python -m pytest -c selftests/pytest.ini selftests/test_gdpr.py`; CI runs them all on every pull request.

```powershell
python -m pip install -r requirements-dev.txt
python -m pytest -c selftests/pytest.ini selftests -n auto    # every push and pull request in CI (~6 min on 4 cores)
python -m pytest -c selftests/pytest.ini selftests -m load -s # by hand (Actions -> Extended tests): load / performance numbers
python -m pytest -c selftests/pytest.ini selftests -m live    # by hand (Actions -> Extended tests): real Claude + Telegram
```

| Area | What is covered |
|------|-----------------|
| Config | every setting: valid, boundary, wrong type, missing, `${ENV}` values, broken YAML |
| Browser | pass, missing element, slow page, HTTP 500, redirect loop, offline, DNS failure, bad TLS certificate, throttled network, fixture error, skip, xfail, and the artifacts each leaves |
| CLI | exit codes, test selection, no tests, bad/missing config, Ctrl-C, same-second runs, unwritable reports folder, no `ffmpeg`, `--open` without a browser |
| Email | plain, STARTTLS, implicit TLS, untrusted certificates, login ok/wrong/missing, rejected recipients, server down, slow server, large report |
| Telegram | document + caption, chat discovery, 400/401/429/500/502, broken JSON, timeout, connection refused, caption limit, token never leaked |
| Claude | request contents, no call on green runs, 400/401/404, 429 retry, 500/529 give-up, refusal, timeout, prompt size cap, failures never break the run |
| Security | report escaping (test names, messages, AI text, media paths), dashboard XSS, path traversal and symlink escape, CSRF, DNS rebinding, loopback-only binding, secret scan of all output and artifacts, `pip-audit`, `bandit` |
| Accessibility | our report and dashboard meet WCAG 2.2 AA (axe, keyboard, focus, reflow, text alternatives); scanning of accessible and broken pages; standards and thresholds |
| Website requirements | compliant vs non-compliant shop page: tracking cookies and tracker requests before consent, accept-only banners, missing or broken links, company details |
| GDPR and cookies | a good and two bad cookie banners: tracking before a choice, no reject button, tiny reject that doesn't stop tracking, pre-ticked boxes, Art. 13 notice items, forms; a small organisation's notice without a DPO |
| Security (safe checks) | a well-set-up and a badly set-up server over HTTP and HTTPS (test certificate authority): headers, versions, cookie flags, private files found by contents and never shown, browsable folders, CORS, plain-http files, certificate expiry and trust |
| Languages | a site in English, Irish and German done right, and each common mistake: no or wrong `lang`, placeholders and keys showing, garbled text, untranslated pages, missing hreflang links back, right-to-left pages |
| Compatibility | the grid (worst result per browser over roles, a column per computer), a real two-browser run with phones, combining runs from two computers |
| Reliability | up, error and no-answer servers, a network that refuses the site (not checked, never down), MTBF / MTTR worked by hand, the private page doing the same sums in a browser, MCP servers up only after the handshake |
| MCP servers | real MCP servers over streamable HTTP, HTTP+SSE and stdio, one good and one with every problem planted: handshake, lists, speed, Origin, CORS, logins and OAuth details, tool poisoning, roles, versions, read-only calls only |
| Load | dashboard with 2,000 runs under 16 concurrent clients, 5 MB report downloads, a 500-test run, concurrent CLI runs, report size budget |

The `CLI` also honours `WEB_UI_REPORTS_DIR` (where run folders go) and `TELEGRAM_API_BASE` (Bot API address).

## Dashboard (optional local UI)

Browse past runs and trigger new ones from a small local web page instead of the CLI:

```powershell
python -m pip install -r requirements-ui.txt
python -m ui_automation --ui
```

Opens at `http://127.0.0.1:8501` by default (`--ui-port` to change it). Lists every run under
`reports/` with pass/fail/skip/error counts, a **Run tests** button, and a link to each run's
HTML report.

## Playwright best practices in this repo

- **Locators** in page objects under `pages/` — `get_by_role`, `get_by_label`, `get_by_test_id` (not CSS/XPath-only).
- **Assertions** — `expect(locator).to_be_visible()` etc. (auto-retrying).
- **Navigation** — relative URLs with `base_url` (`page.goto("/path")`).
- **No arbitrary sleeps** — timeouts from `timeout_ms` and Playwright auto-wait.
- **`strict_selectors: true`** — ambiguous locators fail fast.
- **Isolation** — fresh browser context per test (`pytest-playwright`).
- **Artifacts** — video, trace, and step screenshots for debugging.

## Video recording (local + CI)

`config/settings.yaml`:

```yaml
artifacts:
  video: on   # on | retain-on-failure | off
```

The CLI passes `--video` and stores output under `reports/<timestamp>/playwright-output/`, then copies `.webm` files to `reports/<timestamp>/videos/`.

In **GitHub Actions** (`CI=true`), video is always forced to `on`. The workflow installs `ffmpeg` (for the MP4 copies) and uploads four artifacts: `test-report` (summary + full HTML report), `test-videos`, `test-screenshots` and `playwright-traces`.

## Claude Sonnet 5.5 (AI)

Uses the Anthropic API with model **`claude-sonnet-5-5`**.

1. Set `ANTHROPIC_API_KEY`.
2. In `config/settings.yaml`:

```yaml
ai:
  enabled: true
  model: claude-sonnet-5-5
  max_tokens: 2048
```

After each run, a short failure/success analysis is written to `claude_summary.txt` and included in email/Telegram when those channels are enabled.

## Email notifications

```yaml
notifications:
  email:
    enabled: true
    smtp_host: smtp.example.com
    smtp_port: 587
    smtp_user: "${EMAIL_SMTP_USER}"
    smtp_password: "${EMAIL_SMTP_PASSWORD}"
    from_addr: automation@example.com
    to_addrs:
      - qa@example.com
```

Environment variables replace `${VAR}` placeholders in YAML.

## Telegram notifications

```yaml
notifications:
  telegram:
    enabled: true
    bot_token: "${TELEGRAM_BOT_TOKEN}"
    chat_id: "${TELEGRAM_CHAT_ID}"
```

Create a bot via [@BotFather](https://t.me/BotFather), add the bot to a chat, and use your chat id.

## Project layout

```
SiteSweep/
  config/                  # settings files; your own apps' go in config/private/ (git-ignored)
  site_audit/              # the whole-site audit
  reliability/             # the private uptime page each person publishes for themselves (/reliability)
  tests/                   # accessibility and website-requirement checks of base_url
  practice_sites/          # suites for public practice websites
  pages/base_page.py       # semantic helpers + step() for page objects
  ui_automation/           # command line, settings, browsers, network check, reports, Claude/email/Telegram,
                           # gdpr.py, security.py, localization.py, reliability.py, mcp_audit.py
  selftests/               # the framework's own tests
  .claude/                 # /test, /test-mcp and /reliability, and cloud session setup
  .github/                 # workflows (all started by hand), Dependabot, Sponsor button
  LICENSE, NOTICE          # Apache License 2.0 and the attribution notice
  AGENTS.md, CLAUDE.md     # instructions for AI assistants
```

## Running tests

```powershell
python -m ui_automation
python -m ui_automation -- --headed --slowmo=300
```

## CI secrets (GitHub)

| Secret | Purpose |
|--------|---------|
| `ANTHROPIC_API_KEY` | Claude summaries |
| `TELEGRAM_BOT_TOKEN` | Telegram bot |
| `TELEGRAM_CHAT_ID` | Telegram destination |
| `EMAIL_SMTP_USER` / `EMAIL_SMTP_PASSWORD` | SMTP auth |

Enable notification blocks in `settings.yaml` (or use `settings.example.yaml` as a template).

## Adding tests

1. Add a page object under `pages/` that extends `BasePage`, with its locators.
2. Use role/label locators (`get_by_role`, `get_by_label`).
3. Call `self.step("...")` for HTML report screenshots.
4. Add tests under `tests/`.

## Licence and credit

SiteSweep was created by **Charley Rutledge** and is licensed under the [Apache License 2.0](LICENSE).
By using, copying, changing or sharing it, you accept the terms of that licence.

You're free to use it, change it and share it, including commercially. If you share SiteSweep, or something
based on it:

- include the [`LICENSE`](LICENSE) and [`NOTICE`](NOTICE) files;
- credit **Charley Rutledge** as the creator, with a link to https://github.com/CharleyRutledge/SiteSweep;
- mark the files you changed.

AI assistants working in a copy of SiteSweep are told the same in [`AGENTS.md`](AGENTS.md) and
[`CLAUDE.md`](CLAUDE.md): they mention the creator and the licence when they start, and keep the credit in place.

## Support this project

If SiteSweep saves you time, you can support its development with a small donation:

**[Buy Me a Coffee](https://buymeacoffee.com/charleyrutledge)**

You can also use the **Sponsor** button at the top of this repository.
