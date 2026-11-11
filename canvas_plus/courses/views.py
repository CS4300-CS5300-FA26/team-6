"""Views for the student's current Canvas courses."""
import requests

from django.contrib.auth.decorators import login_required
from django.core.exceptions import ImproperlyConfigured
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.debug import sensitive_variables

from accounts.canvas_client import (
    CanvasAPIError,
    CanvasAuthenticationError,
    canvas_base_url,
    canvas_origin,
    get_course_syllabus,
    list_courses,
    list_upcoming_assignments,
)
from accounts.course_cache import cached_courses
from accounts.models import CanvasConnection, SavedTokenError
from .current import is_current
from .syllabus import FILE_LINK_CLASS, clean_syllabus


@sensitive_variables("token")
def _load_from_canvas(user, load):
    """Load data with the saved connection and one session; return failures as page state."""
    connection = CanvasConnection.objects.filter(user=user).first()
    if connection is None:
        return None, {"canvas_connection_missing": True}
    if not connection.is_valid:
        return None, {"canvas_connection_expired": True}
    try:
        if canvas_origin(connection.canvas_url) != canvas_origin(canvas_base_url()):
            raise SavedTokenError("The configured Canvas host changed.")
        token = connection.get_token()
        with requests.Session() as session:
            return load(connection, token, session), {}
    except (CanvasAuthenticationError, SavedTokenError):
        connection.is_valid = False
        connection.save(update_fields=["is_valid", "updated_at"])
        return None, {"canvas_connection_expired": True}
    except (CanvasAPIError, ImproperlyConfigured):
        return None, {"canvas_unavailable": True}


@sensitive_variables("token")
def _current_courses(connection, token, session):
    """The student's courses whose term hasn't ended."""
    now = timezone.now()
    courses = cached_courses(connection, token, session, list_courses)
    return [course for course in courses if is_current(course, now)]


@sensitive_variables("token")
def _assignments_context(token, courses, session):
    """Keep course navigation available when coursework temporarily cannot load."""
    try:
        return {"assignments": list_upcoming_assignments(token, courses, session=session)}
    except CanvasAuthenticationError:
        raise
    except CanvasAPIError:
        return {"assignments_unavailable": True}


@login_required
def course_list(request):
    """Show active course tabs and upcoming coursework across all current courses."""
    @sensitive_variables("token")
    def load(connection, token, session):
        courses = _current_courses(connection, token, session)
        return {"courses": courses, **_assignments_context(token, courses, session)}

    context, state = _load_from_canvas(request.user, load)
    return render(request, "courses/course_list.html", {**(context or {}), **state})


@login_required
def course_detail(request, course_id):
    """Show one of the student's current courses with its cleaned syllabus."""

    @sensitive_variables("token")
    def load(connection, token, session):
        # Only courses in the student's own list are requested, so Canvas is never
        # asked about a course that could reject the token and expire the connection.
        course = next((c for c in _current_courses(connection, token, session)
                       if c["id"] == course_id), None)
        if course is None:
            return None
        syllabus = get_course_syllabus(token, course_id, session=session)
        return course, syllabus, _assignments_context(token, [course], session)

    found, state = _load_from_canvas(request.user, load)
    if found is None and not state:
        return render(request, "courses/course_detail.html", {"not_found": True}, status=404)
    context = dict(state)
    if found:
        course, syllabus, assignments_context = found
        context.update(assignments_context)
        context["course"] = course
        context["syllabus"] = clean_syllabus(syllabus, canvas_base_url())
        context["has_files"] = f'class="{FILE_LINK_CLASS}"' in context["syllabus"]
    return render(request, "courses/course_detail.html", context)
