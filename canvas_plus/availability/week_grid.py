"""The weekly availability grid on the Study Plan page: what it shows and how a save changes it.

The grid shows today's week, Monday to Sunday, in one-hour blocks. Selected blocks
are stored as ordinary Availability rows, with touching blocks merged into one period.
Times the grid cannot show (9:30-10:15, 9 PM) and days before today are never
changed by a save.

Times are worked in minutes since midnight, so 9:30 AM is 570 and period
arithmetic is integer comparison.
"""

import re
from collections import defaultdict
from datetime import date, time, timedelta

from django.db import transaction

from .models import Availability

GRID_HOURS = range(8, 20)  # one-hour blocks from 8 AM; the last is 7-8 PM
BLOCK_VALUE = re.compile(r"([0-9]{4}-[0-9]{2}-[0-9]{2})T([0-9]{2})")


def block_value(day, hour):
    """The value a grid checkbox carries: 2020-11-19 at 10 AM is "2020-11-19T10"."""
    return f"{day:%Y-%m-%d}T{hour:02d}"


def parse_block(value):
    """ "2020-11-19T10" as (date(2020, 11, 19), 10); anything else as None.

    Values come from the request, so a malformed one is ignored rather than raising.
    """
    match = BLOCK_VALUE.fullmatch(value)
    if not match:
        return None
    try:
        day = date.fromisoformat(match.group(1))
    except ValueError:
        return None
    hour = int(match.group(2))
    return (day, hour) if hour < 24 else None


def week_of(today):
    """Monday to Sunday of the week containing today."""
    monday = today - timedelta(days=today.weekday())
    return [monday + timedelta(days=offset) for offset in range(7)]


def minutes(clock):
    """A time as minutes since midnight: 9:30 is 570."""
    return clock.hour * 60 + clock.minute


def clock_at(total):
    """Minutes since midnight as a time: 570 is 9:30."""
    return time(total // 60, total % 60)


def hour_span(hour):
    """The block starting at hour, in minutes: 10 is (600, 660)."""
    return (hour * 60, hour * 60 + 60)


def merge(intervals):
    """Sorted, non-overlapping intervals; touching ones (10-11 and 11-12) become one."""
    merged = []
    for start, end in sorted(intervals):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def covers(merged, hour):
    """Whether one interval contains the whole hour."""
    start, end = hour_span(hour)
    return any(s <= start and end <= e for s, e in merged)


def without(intervals, cut):
    """The intervals with the cut span removed, splitting any interval it falls inside."""
    cut_start, cut_end = cut
    kept = []
    for start, end in intervals:
        if end <= cut_start or cut_end <= start:
            kept.append((start, end))
            continue
        if start < cut_start:
            kept.append((start, cut_start))
        if cut_end < end:
            kept.append((cut_end, end))
    return kept


def periods_by_day(user, days):
    """Each day's (start, end) minutes for the user, in one query."""
    by_day = defaultdict(list)
    rows = Availability.objects.filter(  # pylint: disable=no-member
        user=user, date__in=days
    ).values_list("date", "start_time", "end_time")
    for day, start, end in rows:
        by_day[day].append((minutes(start), minutes(end)))
    return by_day


def week_grid(user, today):
    """Monday to Sunday of today's week, with each day's blocks and whether they are selected.

    Each day is {"date", "editable", "blocks"}, and each block {"hour", "value", "selected"}.
    A block is selected only when the whole hour is covered, by one period or by
    touching periods merged together (10:00-11:30 and 11:30-12:00 cover 10 and 11).
    """
    days = week_of(today)
    by_day = periods_by_day(user, days)
    grid = []
    for day in days:
        merged = merge(by_day[day])
        grid.append({
            "date": day,
            "editable": day >= today,
            "blocks": [
                {"hour": hour, "value": block_value(day, hour), "selected": covers(merged, hour)}
                for hour in GRID_HOURS
            ],
        })
    return grid


def save_week(user, today, values):
    """Replace this week's selectable whole-hour time with the submitted blocks.

    values is request.POST.getlist("block"); an empty list clears the selectable time.
    Blocks that are malformed, outside grid hours, before today, or outside this
    week are ignored. On each day from today to Sunday, the whole hours the grid
    showed are replaced by the submitted ones and everything else is kept.
    """
    editable = [day for day in week_of(today) if day >= today]
    submitted = defaultdict(list)  # only editable days are read below, so others are ignored
    for value in values:
        block = parse_block(value)
        if block and block[1] in GRID_HOURS:
            submitted[block[0]].append(hour_span(block[1]))

    with transaction.atomic():
        by_day = periods_by_day(user, editable)
        for day in editable:
            current = sorted(by_day[day])
            shown = merge(current)
            kept = shown
            for hour in GRID_HOURS:
                if covers(shown, hour):
                    kept = without(kept, hour_span(hour))
            wanted = merge(kept + submitted[day])
            if wanted == current:
                continue  # leave the day's rows (and their ids) alone
            Availability.objects.filter(user=user, date=day).delete()  # pylint: disable=no-member
            Availability.objects.bulk_create([  # pylint: disable=no-member
                Availability(user=user, date=day, start_time=clock_at(s), end_time=clock_at(e))
                for s, e in wanted
            ])
