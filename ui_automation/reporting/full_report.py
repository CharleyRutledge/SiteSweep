"""Makes pytest-html's detailed report (report.html) meet WCAG 2.2 AA, like the rest of SiteSweep's pages.

pytest-html's own page has no language, no main landmark, unlabelled filter boxes, screenshots without text,
log boxes and rows that can't be reached by keyboard, low-contrast grey text, and a fixed 800px width. Its
template is fixed, so the finished file is corrected after the run: a few markup changes, a style sheet, and a
small script for what pytest-html builds in the browser (rows and the environment table).
"""

from __future__ import annotations

import re
from pathlib import Path

MARK = "<!-- sitesweep: accessible -->"

STYLE = """<style id="sitesweep-a11y">
body { min-width: 0; color: #2b2b2b; padding-inline: 16px; }
a { color: #1a5fb4; }
#results-table, #results-table td, .filters button, .collapse button { color: #2b2b2b; }
.filters button:hover, .collapse button:hover { color: #000; }
span.passed, label.passed, .passed .col-result { color: #16794a; }
span.skipped, span.xfailed, span.rerun, label.skipped, label.xfailed, label.rerun, label.retried,
.skipped .col-result, .xfailed .col-result, .rerun .col-result { color: #7a5c00; }
span.error, span.failed, span.xpassed, label.error, label.failed, label.xpassed,
.error .col-result, .failed .col-result, .xpassed .col-result { color: #b3261e; }
.filters label { margin-right: 8px; }
.filters input:disabled + label { color: #555; }
.collapsible td:not(.col-links):hover::after, #environment-header h2:hover::after { color: #555; }
.summary, .controls, .filters { flex-wrap: wrap; }
.summary__data, .summary__spacer { flex: 1 1 auto; }
.summary__reload__button { flex: 0 1 300px; }
div.media { float: none; max-width: 100%; }
.table-scroll { overflow-x: auto; max-width: 100%; }
.logwrapper .logexpander { margin-left: auto; }
.logwrapper .log { overflow-wrap: anywhere; }
:focus-visible { outline: 2px solid #1a5fb4; outline-offset: 2px; }
</style>"""

SCRIPT = """<script id="sitesweep-a11y-script">
(() => {
  // pytest-html builds rows and the environment table in the browser: fix them as they appear.
  const fix = () => {
    document.querySelectorAll('#environment ul > ul:empty').forEach(u => u.remove());
    document.querySelectorAll('#environment ul > :not(li)').forEach(e => {
      const li = document.createElement('li'); e.replaceWith(li); li.append(e);
    });
    document.querySelectorAll('.collapsible .col-result:not([tabindex])').forEach(td => {
      td.tabIndex = 0;
      td.setAttribute('role', 'button');
      td.setAttribute('aria-label', td.textContent.trim() + ': show or hide details');
      td.addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); td.click(); } });
    });
    document.querySelectorAll('.media-container__viewport img:not([alt])').forEach(i => i.alt = 'Screenshot from the test');
    document.querySelectorAll('.logwrapper:not([tabindex])').forEach(l => {
      l.tabIndex = 0; l.setAttribute('role', 'region'); l.setAttribute('aria-label', 'Test log');
    });
  };
  new MutationObserver(fix).observe(document.body, { childList: true, subtree: true });
  fix();
})();
</script>"""


def make_accessible(path: Path) -> bool:
    """Correct `path` in place. Returns False when it isn't a pytest-html report or was already done."""
    try:
        html = path.read_text(encoding="utf-8")
    except OSError:
        return False
    if MARK in html or 'id="results-table"' not in html:
        return False
    html = html.replace("<html>", '<html lang="en">', 1)
    html = html.replace("</head>", f"{STYLE}\n{MARK}\n</head>", 1)
    html = re.sub(r"<body>\s*", "<body>\n<main>\n", html, count=1)
    html = html.replace("<footer>", "</main>\n<footer>", 1)
    html = html.replace('<img src="" />', '<img src="" alt="Screenshot from the test" />', 1)
    html = html.replace('<div class="logwrapper">',
                        '<div class="logwrapper" tabindex="0" role="region" aria-label="Test log">', 1)
    # Each filter box gets its text as a real label.
    html = re.sub(r'<input ([^>]*?)data-test-result="(\w+)"([^>]*)>\s*<span class="(\w+)">([^<]*)</span>',
                  r'<input \1id="filter-\2" data-test-result="\2"\3>'
                  r'<label for="filter-\2" class="\4">\5</label>', html)
    for table, label in (("environment", "Environment"), ("results-table", "Test results")):
        start = html.find(f'<table id="{table}"')
        end = html.find("</table>", start)
        if start < 0 or end < 0:
            continue
        end += len("</table>")
        html = (html[:start] + f'<div class="table-scroll" tabindex="0" role="region" aria-label="{label}">'
                + html[start:end] + "</div>" + html[end:])
    html = html.replace("</body>", f"{SCRIPT}\n</body>", 1)
    path.write_text(html, encoding="utf-8")
    return True
