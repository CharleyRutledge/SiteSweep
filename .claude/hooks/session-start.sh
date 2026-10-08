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
# The system libraries they need come from the package managers, which the default network access allows.
python -m playwright install-deps chromium firefox webkit \
  || echo "SiteSweep: could not install the browsers' system libraries." >&2
python -m playwright install chromium firefox webkit \
  || echo "SiteSweep: could not download the browsers. Allow cdn.playwright.dev and playwright.download.prss.microsoft.com in the environment's network access." >&2
