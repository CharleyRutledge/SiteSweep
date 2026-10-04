#!/bin/bash
# Claude Code on the web: install what the tests need, so `/test` can run straight away.
# (On your own computer this does nothing: there /test updates the code and packages itself.)
set -euo pipefail
if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi
cd "$CLAUDE_PROJECT_DIR"
python -m pip install --quiet --disable-pip-version-check -r requirements-dev.txt
# Every browser (Chrome's engine, Firefox, Safari's engine). Needs the environment's network access to allow
# cdn.playwright.dev and playwright.download.prss.microsoft.com; without them the session still starts, and
# runs use the Chromium that comes with it.
python -m playwright install --with-deps chromium firefox webkit \
  || echo "SiteSweep: could not download the browsers. Allow cdn.playwright.dev and playwright.download.prss.microsoft.com in the environment's network access." >&2
