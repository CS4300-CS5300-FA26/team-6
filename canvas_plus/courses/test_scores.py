"""Tests for the Canvas score template filter."""
import pytest

from courses.templatetags.scores import score


@pytest.mark.parametrize("value, expected", [
    (99.43, "99.43"),
    (92.5, "92.5"),
    (88.0, "88"),
    (0, "0"),
    (100, "100"),
    (12.345, "12.35"),
    (None, None),
])
def test_score_matches_canvas_precision(value, expected):
    """Scores keep up to two decimals like Canvas, without trailing zeros."""
    assert score(value) == expected
