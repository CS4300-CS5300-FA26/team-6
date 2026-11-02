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


@login_required
@sensitive_variables("token")
def course_list(request):
    """Show the signed-in student's current Canvas courses."""
    context = {"courses": []}
    connection = CanvasConnection.objects.filter(user=request.user).first()
    if connection is None:
        context["canvas_connection_missing"] = True
    elif not connection.is_valid:
        context["canvas_connection_expired"] = True
    else:
        try:
            if canvas_origin(connection.canvas_url) != canvas_origin(canvas_base_url()):
                raise SavedTokenError("The configured Canvas host changed.")
            token = connection.get_token()
            now = timezone.now()
            context["courses"] = [c for c in list_courses(token) if is_current(c, now)]
        except (CanvasAuthenticationError, SavedTokenError):
            connection.is_valid = False
            connection.save(update_fields=["is_valid", "updated_at"])
            context["canvas_connection_expired"] = True
        except (CanvasAPIError, ImproperlyConfigured):
            context["courses_unavailable_message"] = (
                "Unable to load your courses. Please try again."
            )
    return render(request, "courses/course_list.html", context)
