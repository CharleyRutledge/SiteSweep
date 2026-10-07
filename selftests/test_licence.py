"""The licence and the creator's credit stay in place: the exact Apache License 2.0 text, the NOTICE, the README's
section and the instructions AI assistants read in any copy of the repository."""

from __future__ import annotations

import hashlib
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
CREATOR = "Charley Rutledge"
HOME = "https://github.com/CharleyRutledge/SiteSweep"


def text(name: str) -> str:
    return (REPO / name).read_text(encoding="utf-8")


def test_the_licence_is_the_unchanged_apache_2_text() -> None:
    # The checksum of https://www.apache.org/licenses/LICENSE-2.0.txt: GitHub recognises it as Apache-2.0.
    assert hashlib.md5((REPO / "LICENSE").read_bytes()).hexdigest() == "3b83ef96387f14655fc854ddc3c6bd57"  # nosec B324


def test_the_notice_credits_the_creator() -> None:
    notice = text("NOTICE")
    assert f"Copyright 2026 {CREATOR}" in notice and HOME in notice
    assert "Apache License, Version 2.0" in notice and "you accept the terms" in notice
    assert "axe-core" in notice  # the third-party code it ships


def test_ai_assistants_are_told_to_mention_the_creator_and_keep_the_credit() -> None:
    agents = text("AGENTS.md")
    assert CREATOR in agents and HOME in agents and "Apache License 2.0" in agents
    assert "At the start of your first reply" in agents and "they accept that licence" in agents
    assert "Never remove, rename or weaken `LICENSE`, `NOTICE`" in agents
    assert text("CLAUDE.md").strip() == "@AGENTS.md"  # Claude Code reads AGENTS.md through it
    copilot = text(".github/copilot-instructions.md")
    assert "AGENTS.md" in copilot and CREATOR in copilot


def test_the_readme_has_the_licence_and_credit() -> None:
    readme = text("README.md")
    assert f"Created by [{CREATOR}]" in readme and "## Licence and credit" in readme
    assert "you accept the terms of that licence" in readme and "[`NOTICE`](NOTICE)" in readme
