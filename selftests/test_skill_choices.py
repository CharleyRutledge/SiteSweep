"""/test asks what kind of testing to run and turns the answer into `-k` words (.claude/skills/test/SKILL.md):
every check of the site audit must belong to exactly one choice, so none can never be chosen."""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def _choices() -> dict[str, list[str]]:
    table = (REPO / ".claude" / "skills" / "test" / "SKILL.md").read_text(encoding="utf-8")
    rows = re.findall(r"^\| ([^|]+?) \| `([^`]+)` \|$", table, flags=re.M)
    return {choice: words.split(" or ") for choice, words in rows}


def test_every_audit_check_belongs_to_exactly_one_choice() -> None:
    choices = _choices()
    assert set(choices) == {"Pages, links and speed", "Accessibility", "Phones and screen sizes",
                            "Security, logins and API", "Languages and translations",
                            "Irish/EU website requirements",
                            "GDPR and cookies"}, choices
    source = (REPO / "site_audit" / "test_site_audit.py").read_text(encoding="utf-8")
    checks = [c for c in re.findall(r"^def (test_\w+)\(", source, flags=re.M) if c != "test_crawl_found_the_site"]
    for check in checks:
        owners = [choice for choice, words in choices.items() if any(w in check for w in words)]
        assert len(owners) == 1, f"{check} belongs to {owners or 'no choice'}: update the table in SKILL.md"
    assert not any("crawl" in w for words in choices.values() for w in words)  # always added on its own


def test_each_question_offers_at_most_four_options() -> None:
    """AskUserQuestion shows at most four options per question."""
    text = (REPO / ".claude" / "skills" / "test" / "SKILL.md").read_text(encoding="utf-8")
    text = text.split("## 2. Ask what to test", 1)[1].split("\n## ", 1)[0]
    for number in ("3", "4"):
        block = re.split(r"\n\d\. \*\*|\n\n", text.split(f"\n{number}. **", 1)[1], maxsplit=1)[0]
        options = re.findall(r'^   - "', block, flags=re.M)
        assert 2 <= len(options) <= 4, (number, len(options))


def test_a_website_chosen_without_an_address_is_asked_for_again() -> None:
    text = (REPO / ".claude" / "skills" / "test" / "SKILL.md").read_text(encoding="utf-8")
    assert "You chose a website but didn't give its address. What address should I test (for example example.ie)?" in text
