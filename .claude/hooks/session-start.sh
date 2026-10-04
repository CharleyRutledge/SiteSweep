#!/bin/bash
# Claude Code on the web: install what the tests need, so `/test` can run straight away.
# (On your own computer this does nothing: there /test updates the code and packages itself.)
set -euo pipefail

if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

cd "$CLAUDE_PROJECT_DIR"
python -m pip install --quiet --disable-pip-version-check -r requirements-dev.txt
