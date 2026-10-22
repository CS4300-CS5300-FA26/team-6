"""Read enrolled courses and assignments from Canvas without exposing tokens."""

from datetime import datetime, timezone
from urllib.parse import urlsplit

import requests
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.views.decorators.debug import sensitive_variables

MAX_COURSE_PAGES = 100

class CanvasAPIError(Exception):
    """Canvas could not provide a usable response; credentials may still be valid."""


class CanvasAuthenticationError(CanvasAPIError):
    """Canvas rejected the supplied access token."""


def canvas_origin(url):
    """Reject credential-bearing URLs and compare effective scheme/host/port."""
    parsed = urlsplit(url)
    if (parsed.scheme not in {"https", "http"} or not parsed.hostname
            or parsed.username is not None or parsed.password is not None or parsed.fragment):
        raise ValueError("Invalid Canvas URL")
    return parsed.scheme, parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80)


def canvas_base_url():
    """Require a configured HTTPS origin; permit HTTP only for loopback testing."""
    base_url = settings.CANVAS_BASE_URL.rstrip("/")
    try:
        origin = canvas_origin(base_url)
        parsed = urlsplit(base_url)
        if parsed.path or parsed.query:
            raise ValueError("Canvas base URL must contain only the origin")
        if origin[0] != "https" and origin[1] not in {"127.0.0.1", "localhost", "::1"}:
            raise ValueError("Canvas requires HTTPS")
    except ValueError:
        raise ImproperlyConfigured(
            "Configure CANVAS_BASE_URL with your school's HTTPS origin."
        ) from None
    return base_url


@sensitive_variables("token", "response")
def list_courses(token):
    """Return all active student courses, following same-origin pagination only."""
    base_url = canvas_base_url()
    courses = []
    next_url = f"{base_url}/api/v1/courses"
    params = {"enrollment_type": "student", "enrollment_state": "active"}
    visited = set()


    while next_url:
        try:
            safe_origin = canvas_origin(next_url) == canvas_origin(base_url)
        except ValueError:
            safe_origin = False
        if not safe_origin or next_url in visited or len(visited) >= MAX_COURSE_PAGES:
            raise CanvasAPIError("Canvas returned an unsafe or repeated pagination link.")
        visited.add(next_url)

        try:
            response = requests.get(
                next_url,
                headers={"Authorization": f"Bearer {token}"},
                params=params,
                timeout=10,
                allow_redirects=False,
            )
        except requests.RequestException:
            raise CanvasAPIError("Canvas is temporarily unavailable. Please try again.") from None
        if response.status_code == 401:
            raise CanvasAuthenticationError("Canvas rejected the token.")

        if response.status_code != 200:
            raise CanvasAPIError("Canvas could not load your courses. Please try again.")
        try:
            page = response.json()
        except ValueError:
            raise CanvasAPIError(
                "Canvas returned an unreadable response. Please try again."
            ) from None
        if not isinstance(page, list) or any(
            not isinstance(course, dict) or not isinstance(course.get("name"), str)
            for course in page
        ):
            raise CanvasAPIError("Canvas returned unexpected course data. Please try again.")
        courses.extend(page)

        next_url = response.links.get("next", {}).get("url")
        params = None

    return courses


def _validate_assignment_course(course):
    """Reject malformed course results before constructing a Canvas URL."""
    if (not isinstance(course, dict) or isinstance(course.get("id"), bool)
            or not isinstance(course.get("id"), int) or course["id"] <= 0
            or not isinstance(course.get("name"), str)):
        raise CanvasAPIError("Canvas returned unexpected course data. Please try again.")


def _safe_assignment_page_url(next_url, base_url, visited):
    """Validate origin and pagination bounds before sending the bearer token."""
    try:
        safe_origin = canvas_origin(next_url) == canvas_origin(base_url)
    except ValueError:
        safe_origin = False
    if not safe_origin or next_url in visited or len(visited) >= MAX_COURSE_PAGES:
        raise CanvasAPIError("Canvas returned an unsafe or repeated pagination link.")


@sensitive_variables("token", "response")
def _fetch_assignment_page(next_url, token, params):
    """Fetch and validate one Canvas assignment page."""
    try:
        response = requests.get(
            next_url,
            headers={"Authorization": f"Bearer {token}"},
            params=params,
            timeout=10,
            allow_redirects=False,
        )
    except requests.RequestException:
        raise CanvasAPIError(
            "Canvas is temporarily unavailable. Please try again."
        ) from None
    if response.status_code == 401:
        raise CanvasAuthenticationError("Canvas rejected the token.")
    if response.status_code != 200:
        raise CanvasAPIError(
            "Canvas could not load upcoming assignments. Please try again."
        )
    try:
        page = response.json()
    except ValueError:
        raise CanvasAPIError(
            "Canvas returned an unreadable response. Please try again."
        ) from None
    if not isinstance(page, list):
        raise CanvasAPIError(
            "Canvas returned unexpected assignment data. Please try again."
        )
    return page, response.links.get("next", {}).get("url")


def _normalize_assignment(assignment, course_name):
    """Validate and normalize one Canvas assignment result."""
    if (not isinstance(assignment, dict)
            or not isinstance(assignment.get("name"), str)
            or (assignment.get("due_at") is not None
                and not isinstance(assignment["due_at"], str))):
        raise CanvasAPIError(
            "Canvas returned unexpected assignment data. Please try again."
        )
    due_date = None
    if assignment.get("due_at") is not None:
        try:
            parsed_date = datetime.fromisoformat(
                assignment["due_at"].replace("Z", "+00:00")
            )
            if parsed_date.utcoffset() is None:
                raise ValueError("Assignment due date must include a timezone.")
            due_date = parsed_date.astimezone(timezone.utc)
        except ValueError:
            raise CanvasAPIError(
                "Canvas returned an invalid assignment due date. Please try again."
            ) from None
    return {
        "title": assignment["name"],
        "course_name": course_name,
        "due_date": due_date,
    }


def _list_course_upcoming_assignments(token, course, base_url):
    """Fetch all upcoming assignment pages for one validated course."""
    next_url = f"{base_url}/api/v1/courses/{course['id']}/assignments"
    params = {"bucket": "upcoming"}
    visited = set()
    assignments = []
    while next_url:
        _safe_assignment_page_url(next_url, base_url, visited)
        visited.add(next_url)
        page, next_url = _fetch_assignment_page(next_url, token, params)
        assignments.extend(
            _normalize_assignment(assignment, course["name"])
            for assignment in page
        )
        params = None
    return assignments


@sensitive_variables("token")
def list_upcoming_assignments(token, courses):
    """Return normalized upcoming assignments for the supplied enrolled courses."""
    base_url = canvas_base_url()
    assignments = []
    for course in courses:
        _validate_assignment_course(course)
        assignments.extend(_list_course_upcoming_assignments(token, course, base_url))
    return assignments
