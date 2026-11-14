"""Checks that shared.css stacks the dashboard on narrow screens.

The project has no browser tests, so these read the stylesheet's rules
rather than the rendered layout.
"""

import re
from pathlib import Path

import pytest

CSS_PATH = Path(__file__).resolve().parents[1] / "static" / "css" / "shared.css"
NARROW = "(max-width: 60rem)"
ONE_COLUMN = "minmax(0, 1fr)"

pytestmark = pytest.mark.unit


def parse_rules(css):
    """Return {(media, selector): {property: value}} for the stylesheet."""
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    rules = {}

    def walk(text, media):
        pos = 0
        while (open_at := text.find("{", pos)) != -1:
            prelude = text[pos:open_at].strip()
            depth, close_at = 1, open_at + 1
            while depth:
                depth += {"{": 1, "}": -1}.get(text[close_at], 0)
                close_at += 1
            body = text[open_at + 1:close_at - 1]
            if prelude.startswith("@media"):
                walk(body, prelude.removeprefix("@media").strip())
            else:
                declarations = dict(
                    (name.strip(), value.strip())
                    for name, _, value in (d.partition(":") for d in body.split(";"))
                    if value
                )
                for selector in prelude.split(","):
                    rules.setdefault((media, selector.strip()), {}).update(declarations)
            pos = close_at

    walk(css, None)
    return rules


@pytest.fixture(name="rules")
def fixture_rules():
    """The parsed rules of shared.css."""
    return parse_rules(CSS_PATH.read_text(encoding="utf-8"))


@pytest.mark.parametrize("selector", [".dashboard", ".week-grid"])
def test_wide_screens_use_several_columns(rules, selector):
    """Guard: the panels and days sit side by side on wide screens."""
    columns = rules[(None, selector)]["grid-template-columns"]
    assert columns != ONE_COLUMN, f"{selector} should have several columns on wide screens"


@pytest.mark.parametrize("selector", [".dashboard", ".week-grid"])
def test_narrow_screens_stack_into_one_column(rules, selector):
    """Panels and days stack vertically on narrow screens."""
    narrow = rules.get((NARROW, selector), {})
    assert narrow.get("grid-template-columns") == ONE_COLUMN, (
        f"{selector} should stack into one column at {NARROW}"
    )


def test_narrow_screens_drop_the_empty_day_height(rules):
    """Stacked days are only as tall as their chips."""
    narrow = rules.get((NARROW, ".week-day"), {})
    assert narrow.get("min-height") == "0", "stacked days should shrink to their chips"


def test_dashboard_cards_keep_everything_but_the_badge_in_column_two(rules):
    """Only the badge sits in a dashboard card's first column, so it stays badge-wide."""
    not_badge = ".dashboard-panel .assignment-card > :not(.assignment-status)"
    assert rules.get((None, not_badge), {}).get("grid-column") == "2", (
        "every card child except the badge should be placed in column 2"
    )
