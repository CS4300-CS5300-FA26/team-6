"""Sort a course's assignments into the Course Hub summary's two views."""
from datetime import datetime, timezone

SUMMARY_LIMIT = 5  # items shown before the "View all" link


def split_assignments(assignments, now):
    """Split released grades/past work from upcoming work, keeping undated work last."""
    upcoming, past = [], []
    for assignment in assignments:
        due = assignment["due_date"]
        if assignment["score"] is not None or (due is not None and due < now):
            past.append(assignment)
        else:
            upcoming.append(assignment)
    upcoming.sort(key=lambda item: item["due_date"] or datetime.max.replace(tzinfo=timezone.utc))
    past.sort(key=lambda item: item["due_date"] or datetime.min.replace(tzinfo=timezone.utc),
              reverse=True)
    return {"upcoming": upcoming, "past": past}
