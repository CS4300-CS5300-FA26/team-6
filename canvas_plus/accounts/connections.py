"""Check saved connections when a student opens their current home page."""

from django.core.exceptions import ImproperlyConfigured

from .canvas_client import (
    CanvasAPIError, CanvasAuthenticationError, canvas_base_url, canvas_origin, list_courses,
)
from .models import CanvasConnection, SavedTokenError


def connection_status(user):
    """Return banner flags without turning an outage into an expired credential."""
    if not user.is_authenticated:
        return {}
    connection = CanvasConnection.objects.filter(user=user).first()
    if connection is None:
        return {}
    if not connection.is_valid:
        return {"canvas_connection_expired": True}
    try:
        if canvas_origin(connection.canvas_url) != canvas_origin(canvas_base_url()):
            raise SavedTokenError("The configured Canvas host changed.")
        list_courses(connection.get_token())
    except (CanvasAuthenticationError, SavedTokenError):
        connection.is_valid = False
        connection.save(update_fields=["is_valid", "updated_at"])
        return {"canvas_connection_expired": True}
    except (CanvasAPIError, ImproperlyConfigured):
        return {
            "canvas_connection_error": "Unable to check Canvas right now. Please try again later."
        }
    return {}
