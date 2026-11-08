"""Persist a student's normalized Canvas assignment snapshot."""

from django.core.cache import cache
from django.db import transaction
from django.views.decorators.debug import sensitive_variables

from .models import Assignment

# Django wires model managers at runtime; pylint cannot infer them without pylint-django.
# pylint: disable=no-member

SYNC_CACHE_SECONDS = 60 * 60
_SYNC_SUCCEEDED = "success"


def sync_canvas_assignments(user, courses, canvas_assignments):
    """Upsert Canvas-owned fields and mark absent assignments in active courses missing."""
    active_course_ids = {course["id"] for course in courses}
    returned_assignment_ids = set()

    with transaction.atomic():
        for canvas_assignment in canvas_assignments:
            assignment_id = canvas_assignment["canvas_assignment_id"]
            returned_assignment_ids.add(assignment_id)
            Assignment.objects.update_or_create(
                user=user,
                canvas_assignment_id=assignment_id,
                defaults={
                    "canvas_course_id": canvas_assignment["canvas_course_id"],
                    "title": canvas_assignment["title"],
                    "course": canvas_assignment["course_name"],
                    "due_date": canvas_assignment["due_date"],
                    "description": canvas_assignment.get("description") or None,
                    "sync_state": "synced",
                },
            )

        missing_assignments = Assignment.objects.filter(
            user=user,
            canvas_course_id__in=active_course_ids,
        )
        if returned_assignment_ids:
            missing_assignments = missing_assignments.exclude(
                canvas_assignment_id__in=returned_assignment_ids
            )
        missing_assignments.update(sync_state="missing")


@sensitive_variables("token")
def sync_canvas_assignments_if_needed(
    user,
    courses,
    connection,
    assignment_fetcher,
):
    """Fetch and persist once per connection version, caching only committed success."""
    cache_key = (
        f"canvas-assignment-sync:{connection.pk}:{connection.updated_at.timestamp()}"
    )
    if cache.get(cache_key) == _SYNC_SUCCEEDED:
        return False

    try:
        canvas_assignments = assignment_fetcher()
        sync_canvas_assignments(user, courses, canvas_assignments)
    except Exception:  # pylint: disable=broad-exception-caught
        Assignment.objects.filter(
            user=user,
            canvas_course_id__in={course["id"] for course in courses},
        ).update(sync_state="failed")
        raise

    cache.set(cache_key, _SYNC_SUCCEEDED, SYNC_CACHE_SECONDS)
    return True
