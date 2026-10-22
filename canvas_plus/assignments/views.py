"""Django views"""
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ImproperlyConfigured
from django.shortcuts import render
from django.views.decorators.debug import sensitive_variables
from accounts.canvas_client import (
    CanvasAPIError,
    CanvasAuthenticationError,
    canvas_base_url,
    canvas_origin,
    list_courses,
    list_upcoming_assignments,
)
from accounts.models import CanvasConnection, SavedTokenError


@login_required
@sensitive_variables("token")
def assignment_list(request):
    """Show the signed-in student's current upcoming Canvas assignments."""
    assignments = []
    unavailable_message = ""
    connection_expired = False
    connection_missing = False
    connection = CanvasConnection.objects.filter(user=request.user).first()

    if connection is None:
        connection_missing = True
    elif not connection.is_valid:
        connection_expired = True
    else:
        try:
            try:
                origins_match = canvas_origin(connection.canvas_url) == canvas_origin(
                    canvas_base_url()
                )
            except ValueError:
                origins_match = False
            if not origins_match:
                raise SavedTokenError("The configured Canvas host changed.")

            token = connection.get_token()
            courses = list_courses(token)
            assignments = list_upcoming_assignments(token, courses)
        except (CanvasAuthenticationError, SavedTokenError):
            connection.is_valid = False
            connection.save(update_fields=["is_valid", "updated_at"])
            connection_expired = True
        except (CanvasAPIError, ImproperlyConfigured):
            unavailable_message = "Unable to load upcoming assignments. Please try again."

    context = {
        "assignments": assignments,
        "canvas_connection_expired": connection_expired,
        "canvas_connection_missing": connection_missing,
        "assignments_unavailable": (
            bool(unavailable_message) or connection_expired or connection_missing
        ),
        "assignments_unavailable_message": unavailable_message,
    }
    return render(request, "assignments/assignment_list.html", context)
