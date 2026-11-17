"""The weekly availability grid on the Study Plan page: what it shows and how a save changes it."""

GRID_HOURS = range(8, 20)  # one-hour blocks from 8 AM; the last is 7-8 PM


def parse_block(value):  # pylint: disable=unused-argument
    """ "2020-11-19T10" as (date(2020, 11, 19), 10); anything else as None."""
    return None


def week_grid(user, today):  # pylint: disable=unused-argument
    """Monday to Sunday of today's week, with each day's blocks and whether they are selected."""
    return []


def save_week(user, today, values):  # pylint: disable=unused-argument
    """Replace this week's selectable whole-hour time with the submitted blocks."""
