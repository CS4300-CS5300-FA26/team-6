"""Views for the student's current Canvas courses."""
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ImproperlyConfigured
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.debug import sensitive_variables

from accounts.canvas_client import (
    CanvasAPIError, CanvasAuthenticationError, canvas_base_url, canvas_origin, list_courses,
)
from accounts.models import CanvasConnection, SavedTokenError
from .current import is_current


@sensitive_variables("token")
def _load_from_canvas(user, load):
    """Call load(token) with the student's saved token; on failure, return the state to show."""
    connection = CanvasConnection.objects.filter(user=user).first()
    if connection is None:
        return None, {"canvas_connection_missing": True}
    if not connection.is_valid:
        return None, {"canvas_connection_expired": True}
    try:
        if canvas_origin(connection.canvas_url) != canvas_origin(canvas_base_url()):
            raise SavedTokenError("The configured Canvas host changed.")
        return load(connection.get_token()), {}
    except (CanvasAuthenticationError, SavedTokenError):
        connection.is_valid = False
        connection.save(update_fields=["is_valid", "updated_at"])
        return None, {"canvas_connection_expired": True}
    except (CanvasAPIError, ImproperlyConfigured):
        return None, {"canvas_unavailable": True}


@sensitive_variables("token")
def _current_courses(token):
    """The student's courses whose term hasn't ended."""
    now = timezone.now()
    return [course for course in list_courses(token) if is_current(course, now)]


@login_required
def course_list(request):
    """Show the signed-in student's current Canvas courses."""
    courses, state = _load_from_canvas(request.user, _current_courses)
    return render(request, "courses/course_list.html", {"courses": courses or [], **state})
