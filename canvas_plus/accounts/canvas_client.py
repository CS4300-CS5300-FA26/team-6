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


def _validate_pagination_url(next_url, base_url, visited):
    """Reject unsafe, repeated, or excessive same-origin pagination links."""
    try:
        safe_origin = canvas_origin(next_url) == canvas_origin(base_url)
    except ValueError:
        safe_origin = False
    if not safe_origin or next_url in visited or len(visited) >= MAX_COURSE_PAGES:
        raise CanvasAPIError("Canvas returned an unsafe or repeated pagination link.")


@sensitive_variables("token", "response")
def _fetch_page(next_url, token, params, failure_message, invalid_response_message):
    """Fetch a JSON list page and its next link with shared Canvas error handling."""
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
        raise CanvasAPIError(failure_message)
    try:
        page = response.json()
    except ValueError:
        raise CanvasAPIError(
            "Canvas returned an unreadable response. Please try again."
        ) from None
    if not isinstance(page, list):
        raise CanvasAPIError(invalid_response_message)
    return page, response.links.get("next", {}).get("url")


@sensitive_variables("token")
def list_courses(token):
    """Return all active student courses, following same-origin pagination only."""
    base_url = canvas_base_url()
    courses = []
    next_url = f"{base_url}/api/v1/courses"
    params = {"enrollment_type": "student", "enrollment_state": "active"}
    visited = set()


    while next_url:
        _validate_pagination_url(next_url, base_url, visited)
        visited.add(next_url)
        page, next_url = _fetch_page(
            next_url,
            token,
            params,
            "Canvas could not load your courses. Please try again.",
            "Canvas returned unexpected course data. Please try again.",
        )
        if any(
            not isinstance(course, dict) or not isinstance(course.get("name"), str)
            for course in page
        ):
            raise CanvasAPIError("Canvas returned unexpected course data. Please try again.")
        courses.extend(page)

        params = None

    return courses


def _validate_assignment_course(course):
    """Reject malformed course results before constructing a Canvas URL."""
    if (not isinstance(course, dict) or isinstance(course.get("id"), bool)
            or not isinstance(course.get("id"), int) or course["id"] <= 0
            or not isinstance(course.get("name"), str)):
        raise CanvasAPIError("Canvas returned unexpected course data. Please try again.")


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


@sensitive_variables("token")
def _list_course_upcoming_assignments(token, course, base_url):
    """Fetch all upcoming assignment pages for one validated course."""
    next_url = f"{base_url}/api/v1/courses/{course['id']}/assignments"
    params = {"bucket": "upcoming"}
    visited = set()
    assignments = []
    while next_url:
        _validate_pagination_url(next_url, base_url, visited)
        visited.add(next_url)
        page, next_url = _fetch_page(
            next_url,
            token,
            params,
            "Canvas could not load upcoming assignments. Please try again.",
            "Canvas returned unexpected assignment data. Please try again.",
        )
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
    assignments.sort(key=lambda assignment: (
        assignment["due_date"] is None,
        assignment["due_date"],
    ))
    return assignments


def _normalize_submission(submission, course_name):
    """Validate one Canvas submission; return None when it has no published grade."""
    invalid = "Canvas returned unexpected submission data. Please try again."
    if (not isinstance(submission, dict)
            or not isinstance(submission.get("assignment"), dict)
            or not isinstance(submission["assignment"].get("name"), str)):
        raise CanvasAPIError(invalid)
    score = submission.get("score")
    if score is not None and (isinstance(score, bool) or not isinstance(score, (int, float))):
        raise CanvasAPIError(invalid)
    if (submission.get("excused") or submission.get("posted_at") is None
            or submission.get("graded_at") is None):
        return None
    try:
        graded_at = datetime.fromisoformat(submission["graded_at"])
        if graded_at.utcoffset() is None:
            raise ValueError("Graded time must include a timezone.")
    except (TypeError, ValueError):
        raise CanvasAPIError(
            "Canvas returned an invalid graded time. Please try again."
        ) from None
    return {
        "assignment": submission["assignment"]["name"],
        "course": course_name,
        "score": None if score is None else float(score),
        "graded_at": graded_at.astimezone(timezone.utc),
    }


@sensitive_variables("token")
def _list_course_graded_submissions(token, course, base_url):
    """Fetch all graded submission pages for one validated course."""
    next_url = f"{base_url}/api/v1/courses/{course['id']}/students/submissions"
    params = {"workflow_state": "graded", "include[]": "assignment"}
    visited = set()
    submissions = []
    while next_url:
        _validate_pagination_url(next_url, base_url, visited)
        visited.add(next_url)
        page, next_url = _fetch_page(
            next_url,
            token,
            params,
            "Canvas could not load graded work. Please try again.",
            "Canvas returned unexpected submission data. Please try again.",
        )
        normalized = (_normalize_submission(submission, course["name"]) for submission in page)
        submissions.extend(grade for grade in normalized if grade is not None)
        params = None
    return submissions


@sensitive_variables("token")
def list_graded_submissions(token, courses):
    """Return the student's published, graded submissions across the supplied courses."""
    base_url = canvas_base_url()
    submissions = []
    for course in courses:
        _validate_assignment_course(course)
        submissions.extend(_list_course_graded_submissions(token, course, base_url))
    return submissions
