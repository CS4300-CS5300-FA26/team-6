"""Persist a student's normalized Canvas assignment snapshot."""

from django.db import transaction

from .models import Assignment

# Django wires model managers at runtime; pylint cannot infer them without pylint-django.
# pylint: disable=no-member


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