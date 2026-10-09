---
name: reliability
description: Set up hourly reliability monitoring (uptime, MTBF, MTTR) for a website, with the history kept in the person's own private claude.ai page and checked by a scheduled Claude Routine on their account.
---

# Reliability monitoring with SiteSweep

Each person's monitoring is theirs alone: their own private page holds the history, their own Routine does the
checks. Nothing about it goes into this repository, and nothing is shared unless they share the page themselves.
Speak plainly: the person may not be a developer.

## 1. Ask what to watch

Use AskUserQuestion:

- **Which addresses.** The home page, plus up to four pages that matter most (contact, shop, booking). Public pages
  only: never logins, never pages behind a password. A plain `example.ie` is fine: add `https://`.
- **How often.** "Every hour" (recommended; the shortest a Routine allows) or "Every 4 hours".

Check that each address starts with `https://` or `http://` and is not on their own computer (`localhost`,
`127.0.0.1`, `192.168.x.x`): a Routine runs in the cloud and can't reach their computer.

## 2. Check the network and try one check

In a cloud session, run `python -m ui_automation.reach <HOME ADDRESS>` first and follow what it says (the
Routine runs in this same environment, so a site this network refuses would only ever show "not checked").

Then run `python -m ui_automation.reliability check <ADDRESSES>` (for an MCP server add `--mcp`, and
`--token-env NAME` if it needs a login: it is up only when it completes the MCP handshake) and show the result in one line per address
(up or down, HTTP status, time in ms). If one is down, ask before going on: it may be a typo.

## 3. Their private page

Publish `reliability/dashboard.html` with the Artifact tool as a new artifact (no `url`), with
`icon: "chart"`, a description such as "Uptime, MTBF and MTTR for <site>, checked every hour", and these
capabilities, so only the owner can read or write the history even if the page is shared later:

```json
{"db": {"rules": [{"path": "", "read": "owner", "write": "owner"}]}}
```

Then store the check from step 2 with the ArtifactData tool on that artifact: `set` the document
`checks/<YYYY-MM-DD>` (the date of the records' `at`, UTC) to `{"day": "<YYYY-MM-DD>", "checks": [<records>]}`.
Read it back once with `get` and confirm the page shows the address.

Tell them: the page is private to them; sharing it is their choice, and even then only they can see the
history (the rules above).

## 4. The Routine

Show them exactly what will be created and ask before creating it (it runs on their account until they stop it):
name, schedule, addresses, and the page it writes to. Then call `create_trigger` with:

- `name`: `SiteSweep reliability: <site host>`
- `cron_expression`: `0 * * * *` for every hour (`0 */4 * * *` for every 4 hours)
- `create_new_session_on_fire`: true, `initiation`: `human_request`
- `prompt` (fill in the addresses and the page link):

```
SiteSweep reliability check. In the SiteSweep repository (github.com/CharleyRutledge/SiteSweep; install its
requirements.txt if `python -c "import ui_automation"` fails), run:
  python -m ui_automation.reliability check <ADDRESSES>   (for MCP servers: add --mcp [--token-env NAME])
Each output line is one JSON record. With the ArtifactData tool on <PAGE LINK>, `get` the document
checks/<YYYY-MM-DD> (the records' "at" date, UTC). If it exists, add the new records to the end of its "checks"
list and `set` it; if not, `set` it to {"day": "<YYYY-MM-DD>", "checks": [<records>]}. Write nothing else,
anywhere: no files in the repository, no commits, no other documents. Never store passwords, cookies or page
contents. Finish with one line: which addresses are up, and which are down with their error.
```

After the first run (within the hour), check `list_triggers` for its last run and read the day's document once.
If the run couldn't write to the page, say so and what it said; don't keep the Routine running silently broken.

## Stopping or changing it

`update_trigger` with `enabled: false` pauses it; `delete_trigger` removes it (its history stays in their page).
To change the addresses, update the Routine's prompt with `update_trigger`.
