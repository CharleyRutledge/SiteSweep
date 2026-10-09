"""Reliability: is the site up, how often does it go down (MTBF) and how long until it's back (MTTR)?

    python -m ui_automation.reliability check https://www.example.ie https://www.example.ie/contact
    python -m ui_automation.reliability check --config config/site-audit.yaml
    python -m ui_automation.reliability stats history.jsonl

`check` asks each address once (an ordinary GET, as a browser would) and prints one JSON record per address. A
scheduled Claude Routine runs it every hour and keeps the records in the person's own private claude.ai page
(see .claude/skills/reliability/SKILL.md), so each person's history is theirs alone and never in this repository.

An address is down when it doesn't answer or answers with an error (HTTP 400 or above). When the network doing
the check refuses the site (a cloud session's allowlist), the check is "not checked", never "down": that is the
checker's network, not the site.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from statistics import mean

TIMEOUT = 30.0


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def check_one(url: str, timeout: float = TIMEOUT) -> dict:
    """One check: {"at", "url", "up" (True/False, or None = not checked), "status", "ms", "error"}."""
    started = time.monotonic()
    record = {"at": _now(), "url": url, "up": None, "status": None, "ms": None, "error": ""}
    request = urllib.request.Request(url, headers={"User-Agent": "SiteSweep reliability check"})
    try:
        # Only the http(s) addresses the person gave (checked in main).
        # A fresh opener reads this moment's proxy settings (HTTPS_PROXY), as the person's network needs.
        with urllib.request.build_opener().open(request, timeout=timeout) as response:  # nosec B310
            record.update(up=response.status < 400, status=response.status)
    except urllib.error.HTTPError as exc:
        record.update(up=False, status=exc.code, error=f"HTTP {exc.code}")
    except (urllib.error.URLError, OSError) as exc:
        reason = str(getattr(exc, "reason", exc))
        if "Tunnel connection failed: 403" in reason:
            record["error"] = "not checked: this computer's network refuses the site"
        else:
            record.update(up=False, error=reason[:200] or type(exc).__name__)
    record["ms"] = int((time.monotonic() - started) * 1000)
    return record


def check(urls: list[str], timeout: float = TIMEOUT) -> list[dict]:
    return [check_one(u, timeout) for u in urls]


def _time(at: str) -> datetime:
    return datetime.strptime(at, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def stats(records: list[dict], url: str) -> dict:
    """Uptime, incidents, MTBF and MTTR for one address from its checks. An incident starts at the first check
    that found it down and ends at the next check that found it up (so with hourly checks, times are to the
    hour). MTBF = time up / incidents; MTTR = mean time from going down to being back up."""
    checks = sorted((r for r in records if r.get("url") == url and r.get("up") is not None), key=lambda r: r["at"])
    out = {"url": url, "checks": len(checks), "not_checked": sum(1 for r in records if r.get("url") == url
                                                                  and r.get("up") is None),
           "uptime_pct": None, "incidents": [], "mtbf_hours": None, "mttr_minutes": None, "down_now": False}
    if not checks:
        return out
    incidents: list[dict] = []
    for r in checks:
        if not r["up"] and (not incidents or incidents[-1]["end"] is not None):
            incidents.append({"start": r["at"], "end": None, "error": r.get("error", "")})
        elif r["up"] and incidents and incidents[-1]["end"] is None:
            incidents[-1]["end"] = r["at"]
    span = (_time(checks[-1]["at"]) - _time(checks[0]["at"])).total_seconds()
    durations = [(_time(i["end"]) - _time(i["start"])).total_seconds() for i in incidents if i["end"]]
    open_down = (_time(checks[-1]["at"]) - _time(incidents[-1]["start"])).total_seconds() \
        if incidents and incidents[-1]["end"] is None else 0
    for i in incidents:
        i["minutes"] = round((_time(i["end"]) - _time(i["start"])).total_seconds() / 60) if i["end"] else None
    out.update(uptime_pct=round(100 * sum(1 for r in checks if r["up"]) / len(checks), 2), incidents=incidents,
               down_now=not checks[-1]["up"])
    if incidents:
        out["mtbf_hours"] = round((span - sum(durations) - open_down) / 3600 / len(incidents), 1)
    if durations:
        out["mttr_minutes"] = round(mean(durations) / 60)
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m ui_automation.reliability", description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    c = sub.add_parser("check", help="Check each address once and print one JSON record per address")
    c.add_argument("urls", nargs="*")
    c.add_argument("--config", help="Or a settings file: its base_url is checked")
    c.add_argument("--timeout", type=float, default=TIMEOUT)
    s = sub.add_parser("stats", help="Uptime, MTBF and MTTR from records (JSON lines, or a JSON list)")
    s.add_argument("file")
    args = parser.parse_args(argv)
    if args.command == "check":
        urls = list(args.urls)
        if args.config:
            from ui_automation.config import load_settings

            urls.append(load_settings(args.config).base_url)
        if not urls or not all(u.lower().startswith(("http://", "https://")) for u in urls):
            print("Give each address starting with http:// or https://", file=sys.stderr)
            return 2
        for record in check(urls, args.timeout):
            print(json.dumps(record))
        return 0
    text = open(args.file, encoding="utf-8").read().strip()
    records = json.loads(text) if text.startswith("[") else [json.loads(line) for line in text.splitlines() if line]
    for url in dict.fromkeys(r["url"] for r in records):
        print(json.dumps(stats(records, url)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
