"""Compatibility: which checks passed in which browser and phone, on which computer, as one grid.

Playwright runs the browsers on the computer doing the test, so a run covers that computer's operating system.
Runs from other computers (a Mac through the Claude Desktop app, a Windows PC) are combined into one grid with:

    python -m ui_automation.reporting.compat reports/<run> reports/<other run> -o compatibility.html
"""

from __future__ import annotations

import argparse
import platform
import sys
from html import escape
from pathlib import Path

from ui_automation.reporting.summary import RunSummary, TestResult

BROWSERS = {"chromium": "Chrome's engine (Chromium)", "firefox": "Firefox", "webkit": "Safari's engine (WebKit)"}
RANK = {"passed": 0, "skipped": 1, "failed": 2, "error": 3}
SYMBOL = {"passed": "✓ passed", "failed": "✕ failed", "error": "✕ error", "skipped": "skipped"}
PHONES_TITLE = "Phones checked"


def environment() -> dict:
    """The computer and browser versions of this run (each browser's version as it was launched)."""
    from ui_automation.firefox_profile import LAUNCHED

    system = platform.system()
    release = platform.mac_ver()[0] if system == "Darwin" else platform.release()
    name = {"Darwin": "macOS"}.get(system, system)
    return {"os": f"{name} {release}".strip(), "browsers": dict(LAUNCHED)}


def _browser(test: TestResult) -> str:
    return next((t for t in test.variant_tags if t in BROWSERS), "")


def grid(runs: list[tuple[dict, list[TestResult]]]) -> tuple[list[str], list[list[str]], list[list[str]]]:
    """(columns, rows, phones): one column per (computer, browser), one row per check, worst outcome over
    roles; '' where a check didn't run in that browser. `phones` lists each phone profile's result."""
    columns: list[tuple[int, str]] = []
    for i, (_, tests) in enumerate(runs):
        used = {_browser(t) for t in tests} - {""}
        columns += [(i, b) for b in BROWSERS if b in used]
    several = len(runs) > 1
    labels = []
    for i, b in columns:
        env = runs[i][0]
        version = env.get("browsers", {}).get(b, "")
        label = BROWSERS[b] + (f" {version}" if version else "")
        labels.append(label + (f" on {env.get('os', '?')}" if several else ""))
    cells: dict[str, dict[int, str]] = {}
    for col, (i, b) in enumerate(columns):
        for t in runs[i][1]:
            if _browser(t) != b:
                continue
            row = cells.setdefault(t.title, {})
            if col not in row or RANK.get(t.outcome, 0) > RANK.get(row[col], 0):
                row[col] = t.outcome
    rows = [[title, *(SYMBOL.get(row.get(c, ""), "") for c in range(len(columns)))] for title, row in cells.items()]
    phones = []
    for env, tests in runs:
        for t in tests:
            for table in t.evidence:
                if table.get("title") == PHONES_TITLE:
                    phones += [list(r) + ([env.get("os", "")] if several else []) for r in table.get("rows", [])]
    return labels, rows, phones


def section(runs: list[tuple[dict, list[TestResult]]]) -> str:
    """The report's Compatibility section ('' when no check ran in a browser)."""
    labels, rows, phones = grid(runs)
    if not rows:
        return ""
    oses = sorted({env.get("os", "") for env, _ in runs} - {""})
    parts = ["<h2>Compatibility</h2>",
             '<p class="about">Each check in each browser'
             + (f", on {escape(', '.join(oses))}" if oses else "")
             + ". A blank cell means the check didn't run in that browser: checks that don't depend on the browser "
               "(links, HTTPS, legal pages) run in the first one only. Browsers run on the computer doing the test; "
               "to add another operating system, run SiteSweep there and combine the runs (see the README).</p>"]
    head = '<th scope="col">Check</th>' + "".join(f'<th scope="col">{escape(c)}</th>' for c in labels)
    body = "".join(
        "<tr>" + f'<th scope="row" data-label="Check">{escape(r[0])}</th>'
        + "".join(f'<td data-label="{escape(labels[i])}" class="{_cls(v)}">{escape(v or "—")}</td>'
                  for i, v in enumerate(r[1:])) + "</tr>"
        for r in rows)
    parts.append('<div class="table-wrap" tabindex="0" role="region" aria-label="Checks in each browser">'
                 '<table class="evidence compat"><caption class="sr-only">Checks in each browser</caption>'
                 f"<thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>")
    if phones:
        cols = ["Phone", "Browser engine", "Pages", "Problems", "Result"] + (["Computer"] if len(runs) > 1 else [])
        head = "".join(f'<th scope="col">{escape(c)}</th>' for c in cols)
        body = "".join("<tr>" + "".join(f'<td data-label="{escape(c)}">{escape(str(v))}</td>' for c, v in zip(cols, r))
                       + "</tr>" for r in phones)
        parts.append('<div class="sub">Phones</div><div class="table-wrap" tabindex="0" role="region" '
                     'aria-label="Phones"><table class="evidence"><caption class="sr-only">Phones</caption>'
                     f"<thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>")
    return "".join(parts)


def _cls(value: str) -> str:
    return "ok" if value.startswith("✓") else "bad" if value.startswith("✕") else ""


PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Compatibility</title><style>
:root {{ --bg:#fff; --fg:#1a1a1a; --muted:#555; --line:#ccc; --ok:#0a6b2d; --bad:#b00020; }}
@media (prefers-color-scheme: dark) {{ :root {{ --bg:#121212; --fg:#eee; --muted:#bbb; --line:#444;
  --ok:#6fdc8c; --bad:#ff8a80; }} }}
body {{ background:var(--bg); color:var(--fg); font:16px/1.5 system-ui, sans-serif; margin:0 auto;
  max-width:1100px; padding:16px; }}
.about, .sub {{ color:var(--muted); }} .sub {{ font-weight:600; margin-top:1.5em; }}
.table-wrap {{ overflow-x:auto; }} table {{ border-collapse:collapse; width:100%; }}
th, td {{ border:1px solid var(--line); padding:6px 8px; text-align:left; vertical-align:top;
  overflow-wrap:anywhere; }}
td.ok {{ color:var(--ok); }} td.bad {{ color:var(--bad); font-weight:600; }}
.sr-only {{ position:absolute; width:1px; height:1px; overflow:hidden; clip:rect(0 0 0 0); }}
</style></head><body><main><h1>Compatibility: {name}</h1>{body}</main></body></html>"""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m ui_automation.reporting.compat",
                                     description="Combine runs from several computers into one compatibility grid.")
    parser.add_argument("runs", nargs="+", help="Run folders (each with a summary.json)")
    parser.add_argument("-o", "--output", default="compatibility.html")
    args = parser.parse_args(argv)
    runs, names = [], set()
    for folder in args.runs:
        path = Path(folder)
        if not (path / "summary.json").is_file():
            print(f"{folder}: no summary.json here", file=sys.stderr)
            return 2
        summary = RunSummary.load(path)
        runs.append((summary.environment, summary.tests))
        names.add(summary.name or summary.base_url)
    html = section(runs) or "<p>No check ran in a browser in these runs.</p>"
    Path(args.output).write_text(PAGE.format(name=escape(", ".join(sorted(names))), body=html), encoding="utf-8")
    print(f"Wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
