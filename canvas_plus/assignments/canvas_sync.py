"""Refresh selected local assignment snapshots from Canvas."""

import requests
from django.core.cache import cache
from django.core.exceptions import ImproperlyConfigured

from accounts.canvas_client import (
    CanvasAPIError,
    CanvasAuthenticationError,
    canvas_base_url,
    canvas_origin,
    list_courses,
    list_upcoming_assignments,
)
from accounts.models import CanvasConnection, SavedTokenError
from assignments.models import Assignment

COURSE_CACHE_SECONDS = 60 * 60

def get_cached_canvas_courses(connection, token, session, course_loader=None):
    """Validate the Canvas host and return its cached or freshly fetched courses."""
    if canvas_origin(connection.canvas_url) != canvas_origin(canvas_base_url()):
        raise SavedTokenError("The configured Canvas host changed.")

    courses_key = f"canvas-courses:{connection.pk}:{connection.updated_at.timestamp()}"
    courses = cache.get(courses_key)
    if courses is None:
        load_courses = course_loader or list_courses
        courses = load_courses(token, session=session)
        cache.set(courses_key, courses, COURSE_CACHE_SECONDS)
    return courses


def upsert_canvas_assignment_snapshot(user, canvas_assignment):
    """Create or refresh one Canvas snapshot without changing local estimates."""
    assignment, _ = Assignment.objects.update_or_create(
        user=user,
        canvas_assignment_id=canvas_assignment["canvas_assignment_id"],
        defaults={
            "canvas_course_id": canvas_assignment["canvas_course_id"],
            "title": canvas_assignment["title"],
            "course": canvas_assignment["course_name"],
            "due_date": canvas_assignment.get("due_date"),
            "description": canvas_assignment.get("description") or "",
        },
    )
    return assignment


def refresh_selected_assignment_snapshots(user, assignments):
    """Refresh Canvas-owned fields for selected rows, retaining snapshots on failure."""
    if not assignments:
        return []

    connection = CanvasConnection.objects.filter(user=user).first()
    if connection is None or not connection.is_valid:
        return _snapshot_fallback_notices(assignments)

    try:
        token = connection.get_token()
        with requests.Session() as session:
            courses = get_cached_canvas_courses(connection, token, session)
            canvas_assignments = list_upcoming_assignments(
                token,
                courses,
                session=session,
            )
    except (CanvasAuthenticationError, SavedTokenError):
        connection.is_valid = False
        connection.save(update_fields=["is_valid", "updated_at"])
        return _snapshot_fallback_notices(assignments)
    except (CanvasAPIError, ImproperlyConfigured):
        return _snapshot_fallback_notices(assignments)

    assignments_by_canvas_id = {
        item["canvas_assignment_id"]: item for item in canvas_assignments
    }
    notices = []
    for assignment in assignments:
        canvas_assignment = assignments_by_canvas_id.get(assignment.canvas_assignment_id)
        if canvas_assignment is None:
            notices.append(
                f"{assignment.title} used saved Canvas details because it was not "
                "returned by Canvas."
            )
            continue

        upsert_canvas_assignment_snapshot(user, canvas_assignment)
        assignment.refresh_from_db(
            fields=["canvas_course_id", "title", "course", "due_date", "description"]
        )
    return notices


def _snapshot_fallback_notices(assignments):
    """Explain that each selected assignment kept its saved Canvas snapshot."""
    return [
        f"{assignment.title} used saved Canvas details because a refresh was unavailable."
        for assignment in assignments
    ]
