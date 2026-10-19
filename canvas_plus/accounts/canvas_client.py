import requests
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

class CanvasAuthenticationError(Exception):
    """Canvas rejected the supplied access token."""

def list_courses(token):
    """Return the student's actively enrolled course list from Canvas"""
    base_url = settings.CANVAS_BASE_URL.rstrip("/")
    if not base_url:
        raise ImproperlyConfigured("Canvas base URL not configured in your .env file")

    response = requests.get(
        f"{base_url}/api/v1/courses",
        headers={"Authorization": f"Bearer {token}"},
        params={
            "enrollment_type": "student",
            "enrollment_state": "active",
        },
        timeout=10
    )

    # Error code 401 is specifically when the API token is rejected. Other errors (403, 429, 500, etc) are handled in response.raise_for_status()
    if response.status_code == 401:
        raise CanvasAuthenticationError("Canvas rejected the token.")

    # Courses require pagination (https://developerdocs.instructure.com/services/canvas/basics/file.pagination)
    courses = []
    next_url = f"{base_url}/api/v1/courses"
    params = {
        "enrollment_type": "student",
        "enrollment_state": "active",
    }

    while next_url is not None:
        response = requests.get(
            next_url,
            headers={"Authorization": f"Bearer {token}"},
            params=params,
            timeout=10,
        )

        if response.status_code == 401:
            raise CanvasAuthenticationError("Canvas rejected the token.")

        response.raise_for_status()
        courses.extend(response.json())

        next_url = response.links.get("next", {}).get("url")
        params = None

    return courses