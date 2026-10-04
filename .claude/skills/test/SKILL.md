---
name: test
description: Get the latest code, ask what to test (a website or a settings file, which browsers), run the site audit and explain the report in plain language. Started by the "Open in Claude" links in the README.
---

# Test a website or app with SiteSweep

Work through these steps in order. Speak plainly: the person running this may not be a developer.

## 1. Get the latest code

Run `echo "${CLAUDE_CODE_REMOTE:-}"` to see where you are.

- **`true` (a cloud session):** the code was just cloned, so it is already the latest. If
  `python -c "import playwright"` fails, run `python -m pip install -r requirements-dev.txt` first. Note that a
  cloud session **cannot reach the person's own computer**: `localhost`, `127.0.0.1` and `192.168.x.x` addresses
  won't work here.
- **Anything else (their own computer):**
  1. Run `git status --short`. If files are changed, **stop and ask** before doing anything: never discard
     their changes. Offer `git stash push -m "before /test"`, which keeps them safe.
  2. Run `git pull --ff-only`, then `python -m pip install -U -r requirements.txt`.
  3. Say in one line what changed (`git log --oneline -5`), or that it was already up to date.

## 2. Ask what to test

Use the AskUserQuestion tool. Ask together:

1. **What to test.** Offer:
   - "A website": then ask for its address.
   - "The practice websites" (`config/practice-sites.yaml`).
   - On their own computer only: each settings file in `config/private/` (git-ignored, their own apps), by its
     `name:`. Never list, name or describe these files anywhere else (no commits, issues or pull requests).
   Don't offer `config/settings.yaml` or `config/settings.example.yaml`: they are templates.
2. **How thorough.** "Quick: today's browser and phone" (the default, about 4 minutes for a small site) or
   "Full: every browser and phone" (`--all-browsers`, about three times longer, good before a release).

Don't ask for passwords. Logins come from the `.env` file on their computer only. If a role's variables are
missing, the run says which ones; tell them to add those lines to `.env` themselves.

## 3. Run it

From the repository folder:

- A website: `python -m ui_automation --config config/site-audit.yaml --url <ADDRESS> [--all-browsers] -- site_audit`
- A settings file: `python -m ui_automation --config <FILE> [--all-browsers] -- site_audit`

The run is read-only: it opens pages and sends GET requests; it never submits forms or changes data.
It can take several minutes; run it in the background and tell the person roughly how long it will take.

If it stops before testing:
- **"Nothing is answering at …"**: the app isn't running. On their computer, ask them to start it (or set
  `app.start` in its settings file), then run again.
- **"Could not install …"** in a cloud session: the environment's network access blocks Playwright's download
  servers. Tell them to add `cdn.playwright.dev` and `playwright.download.prss.microsoft.com` to Allowed domains
  (steps: https://code.claude.com/docs/en/cloud-environments#network-access), then start a new session so every
  browser downloads. Meanwhile, if they agree, run with `-- --browser chromium site_audit`: Chromium is always
  available there. Never work around a browser that won't install by editing the project or linking files.
- **A page answers 403 "request blocked" / "no rule or allowlist entry"**: that is the cloud session's network
  access, not the site. Tell them to add the site's domain to Allowed domains (same steps).

## 4. Explain the result

Read `reports/latest/summary.json` (and `reports/latest/claude_summary.txt` if it exists). Then reply with:

1. **One line:** passed or failed, the site, how many checks passed / failed.
2. **What failed**, grouped by cause, worst first. For each: what's wrong in plain words, which pages / roles /
   browsers, and the fix (the report's suggested fixes are copyable). Group the same problem on many pages as
   one item: it is usually one fix in a shared header, footer or style.
3. **What wasn't run and why** (the "Not run" list at the end of the run), if anything.
4. **Where the full report is:**
   - On their computer: `reports/latest/summary.html` (Ctrl+click the link in the command output).
   - In a cloud session: send `reports/latest/summary.html` with the SendUserFile tool so they can open it.

## Never

- Never show, print or write a password, token or the contents of `.env`.
- Never commit, push or open a pull request from this command unless they ask for a change afterwards.
- Never run anything that changes the app's data.
