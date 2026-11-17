"""Checks that shared.css stacks the dashboard and Study Plan panels on narrow screens.

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


@pytest.mark.parametrize("selector", [".dashboard", ".week-grid", ".study-plan-layout"])
def test_wide_screens_use_several_columns(rules, selector):
    """Guard: the panels and days sit side by side on wide screens."""
    columns = rules[(None, selector)]["grid-template-columns"]
    assert columns != ONE_COLUMN, f"{selector} should have several columns on wide screens"


@pytest.mark.parametrize("selector", [".dashboard", ".week-grid", ".study-plan-layout"])
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


@pytest.mark.parametrize("panel", [".dashboard-panel", ".study-plan-panel"])
def test_panel_cards_keep_everything_but_the_badge_in_column_two(rules, panel):
    """Only the badge sits in a panel card's first column, so it stays badge-wide."""
    card = rules.get((None, f"{panel} .assignment-card"), {})
    assert card.get("grid-template-columns") == "auto minmax(0, 1fr)", (
        f"cards in {panel} should use the two-column layout"
    )
    not_badge = f"{panel} .assignment-card > :not(.assignment-status)"
    assert rules.get((None, not_badge), {}).get("grid-column") == "2", (
        "every card child except the badge should be placed in column 2"
    )


def test_the_availability_grid_keeps_seven_days_on_narrow_screens(rules):
    """A week that stacks one day under another stops being a calendar."""
    assert "repeat(7," in rules[(None, ".availability-grid")]["grid-template-columns"]
    narrow = rules.get((NARROW, ".availability-grid"), {})
    assert "grid-template-columns" not in narrow, "the grid should not be stacked"


def test_each_day_column_is_at_least_a_touch_target_wide(rules):
    """WCAG 2.5.8: a block is at least 24px wide, however narrow the screen."""
    columns = rules[(None, ".availability-grid")]["grid-template-columns"]
    days = re.search(r"repeat\(7,\s*minmax\(([\d.]+)(rem|px),", columns)
    assert days, f"the day columns should have a fixed minimum width, not {columns!r}"
    minimum = float(days.group(1)) * (16 if days.group(2) == "rem" else 1)
    assert minimum >= 24, f"the day columns' minimum is {minimum}px"


def test_the_grid_scrolls_sideways_when_it_does_not_fit(rules):
    """The grid scrolls inside itself, so the page never does."""
    assert rules[(None, ".availability-grid")].get("overflow-x") == "auto"


def test_the_hour_labels_stay_put_while_the_grid_scrolls(rules):
    """Sticky labels need a background, or the cells scrolling under them show through."""
    hours = rules[(None, ".grid-hours")]
    assert hours.get("position") == "sticky"
    assert hours.get("left") == "0"
    assert "background" in hours, "the sticky labels should have a background"
