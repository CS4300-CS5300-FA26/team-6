"""Read enrolled courses and assignments from Canvas without exposing tokens."""

import ipaddress
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from functools import partial
from urllib.parse import urljoin, urlsplit

import requests
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.views.decorators.debug import sensitive_variables

MAX_COURSE_PAGES = 100
# Matches requests' default pool of 10 connections per host; Canvas throttles more parallelism.
MAX_CONCURRENT_REQUESTS = 10
MAX_FILE_BYTES = 25 * 1024 * 1024
REDIRECT_STATUSES = {301, 302, 303, 307, 308}
MAX_FILE_REDIRECTS = 5

class CanvasAPIError(Exception):
    """Canvas could not provide a usable response; credentials may still be valid."""


class CanvasAuthenticationError(CanvasAPIError):
    """Canvas rejected the supplied access token."""


class CanvasFileTooLarge(CanvasAPIError):
    """A Canvas file is bigger than Canvas+ will load."""


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
def _get_json(url, token, params, failure_message, session):
    """Request one Canvas URL and return its JSON and response, with shared error handling."""
    try:
        # requests.get and Session.get share a signature; a session reuses connections.
        response = (session or requests).get(
            url,
            headers={"Authorization": f"Bearer {token}"},
            params=params,
            timeout=10,
            allow_redirects=False,
        )
    except requests.RequestException:
        raise CanvasAPIError("Canvas is temporarily unavailable. Please try again.") from None
    # Canvas adds WWW-Authenticate only when the token itself is invalid or expired.
    # A 401 without it means the token is fine but this item is off limits, like a locked file.
    if response.status_code == 401 and response.headers.get("WWW-Authenticate"):
        raise CanvasAuthenticationError("Canvas rejected the token.")
    if response.status_code != 200:
        raise CanvasAPIError(failure_message)
    try:
        return response.json(), response
    except ValueError:
        raise CanvasAPIError(
            "Canvas returned an unreadable response. Please try again."
        ) from None


@sensitive_variables("token", "response")
# pylint: disable-next=too-many-arguments,too-many-positional-arguments  # each is a distinct request input
def _fetch_page(next_url, token, params, failure_message, invalid_response_message, session):
    """Fetch a JSON list page and its next link with shared Canvas error handling."""
    page, response = _get_json(next_url, token, params, failure_message, session)
    if not isinstance(page, list):
        raise CanvasAPIError(invalid_response_message)
    return page, response.links.get("next", {}).get("url")


@sensitive_variables("token")
def list_courses(token, session=None):
    """Return all active student courses, following same-origin pagination only."""
    base_url = canvas_base_url()
    courses = []
    next_url = f"{base_url}/api/v1/courses"
    params = {
        "enrollment_type": "student",
        "enrollment_state": "active",
        "per_page": 100,
        "include[]": "term",
    }
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
            session,
        )
        if any(
            not isinstance(course, dict) or not isinstance(course.get("name"), str)
            for course in page
        ):
            raise CanvasAPIError("Canvas returned unexpected course data. Please try again.")
        courses.extend(page)

        params = None

    return courses


@sensitive_variables("token")
def get_course_syllabus(token, course_id):
    """Return one course's syllabus HTML, or None when it has none."""
    course, _ = _get_json(
        f"{canvas_base_url()}/api/v1/courses/{course_id}",
        token,
        {"include[]": "syllabus_body"},
        "Canvas could not load this course. Please try again.",
        None,
    )
    if not isinstance(course, dict):
        raise CanvasAPIError("Canvas returned unexpected course data. Please try again.")
    syllabus = course.get("syllabus_body")
    if syllabus is not None and not isinstance(syllabus, str):
        raise CanvasAPIError("Canvas returned unexpected course data. Please try again.")
    return syllabus


@sensitive_variables("token")
def get_course_file(token, course_id, file_id):
    """Return one course file's name, size in bytes, and download address."""
    info, _ = _get_json(
        f"{canvas_base_url()}/api/v1/courses/{course_id}/files/{file_id}",
        token,
        None,
        "Canvas could not load this file. Please try again.",
        None,
    )
    if (not isinstance(info, dict) or not isinstance(info.get("display_name"), str)
            or not isinstance(info.get("url"), str)
            or isinstance(info.get("size"), bool) or not isinstance(info.get("size"), int)):
        raise CanvasAPIError("Canvas returned unexpected file data. Please try again.")
    return {"name": info["display_name"], "size": info["size"], "url": info["url"]}


def _safe_storage_url(url):
    """Allow an HTTPS address unless its host is a private, loopback, or link-local IP.

    A host name passes: HTTPS certificate checks stop it from reaching an internal service.
    """
    try:
        parts = urlsplit(url)
        host = parts.hostname
    except ValueError:
        return False
    if parts.scheme != "https" or not host:
        return False
    try:
        return ipaddress.ip_address(host).is_global
    except ValueError:
        return True


@sensitive_variables("token")
def open_course_file(token, url):
    """Open a streaming response for a Canvas file, sending the token only to our Canvas host.

    The caller must close the response.
    """
    try:
        on_canvas = canvas_origin(url) == canvas_origin(canvas_base_url())
    except ValueError:
        on_canvas = False
    if not on_canvas:
        raise CanvasAPIError("Canvas returned an unsafe file address.")
    try:
        response = requests.get(
            url,
            headers={"Authorization": f"Bearer {token}"},
            timeout=10,
            allow_redirects=False,
            stream=True,
        )
        for _ in range(MAX_FILE_REDIRECTS):
            if response.status_code not in REDIRECT_STATUSES:
                break
            # Canvas hands the file off to separate storage, which must never see the token.
            # Each hop is followed here, not by requests, so every address gets checked.
            url = urljoin(url, response.headers.get("Location", ""))
            response.close()
            if not _safe_storage_url(url):
                raise CanvasAPIError("Canvas returned an unsafe file address.")
            response = requests.get(url, timeout=30, allow_redirects=False, stream=True)
    except requests.RequestException:
        raise CanvasAPIError("Canvas is temporarily unavailable. Please try again.") from None
    if response.status_code != 200:
        response.close()
        raise CanvasAPIError("Canvas could not load this file. Please try again.")
    return response


@sensitive_variables("token")
def download_course_file(token, url, max_bytes=MAX_FILE_BYTES):
    """Return a Canvas file's bytes, stopping past max_bytes.

    Callers check the file's reported size first; the byte limit here is a backstop.
    """
    response = open_course_file(token, url)
    try:
        body = bytearray()
        for chunk in response.iter_content(chunk_size=64 * 1024):
            body.extend(chunk)
            if len(body) > max_bytes:
                raise CanvasFileTooLarge("This file is too large to preview.")
        return bytes(body)
    except requests.RequestException:  # the connection can also drop mid-download
        raise CanvasAPIError("Canvas is temporarily unavailable. Please try again.") from None
    finally:
        response.close()


def _validate_assignment_course(course):
    """Reject malformed course results before constructing a Canvas URL."""
    if (not isinstance(course, dict) or isinstance(course.get("id"), bool)
            or not isinstance(course.get("id"), int) or course["id"] <= 0
            or not isinstance(course.get("name"), str)):
        raise CanvasAPIError("Canvas returned unexpected course data. Please try again.")


def _normalize_assignment(assignment, course_name, course_id):
    """Validate and normalize one Canvas assignment result."""
    invalid = "Canvas returned unexpected assignment data. Please try again."
    if (not isinstance(assignment, dict)
            or isinstance(assignment.get("id"), bool)
            or not isinstance(assignment.get("id"), int)
            or assignment["id"] <= 0):
        raise CanvasAPIError(invalid)
    if (not isinstance(assignment.get("name"), str)
            or (assignment.get("due_at") is not None
                and not isinstance(assignment["due_at"], str))):
        raise CanvasAPIError(invalid)
    submission = assignment.get("submission")
    if submission is not None and not isinstance(submission, dict):
        raise CanvasAPIError(invalid)
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
    submitted = submission is not None and (
        submission.get("submitted_at") is not None
        or submission.get("workflow_state") == "graded"
        or submission.get("excused") is True
    )
    return {
        "canvas_assignment_id": assignment["id"],
        "canvas_course_id": course_id,
        "title": assignment["name"],
        "course_name": course_name,
        "due_date": due_date,
        "submitted": submitted,
        "description": assignment.get("description"),
    }


@sensitive_variables("token")
def _list_course_upcoming_assignments(token, course, bucket, base_url, session):
    """Fetch all (assignment, id) pairs in one bucket for a validated course."""
    next_url = f"{base_url}/api/v1/courses/{course['id']}/assignments"
    params = {"bucket": bucket, "include[]": "submission", "per_page": 100}
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
            session,
        )
        assignments.extend(
            (_normalize_assignment(assignment, course["name"], course["id"],), assignment.get("id"))
            for assignment in page
        )

        params = None
    return assignments


@sensitive_variables("token")
def list_upcoming_assignments(token, courses, session=None):
    """Return normalized upcoming and overdue assignments with submission status."""
    base_url = canvas_base_url()
    for course in courses:
        _validate_assignment_course(course)
    buckets = ("upcoming", "overdue")
    with ThreadPoolExecutor(MAX_CONCURRENT_REQUESTS) as pool:
        # map yields in input order and re-raises the first failure in that order.
        pages = list(pool.map(
            partial(_list_course_upcoming_assignments, token, base_url=base_url, session=session),
            [course for course in courses for _ in buckets],
            buckets * len(courses),
        ))
    assignments = []
    seen_ids = set()
    for page in pages:
        for assignment, assignment_id in page:
            if assignment_id is not None:
                if assignment_id in seen_ids:
                    continue
                seen_ids.add(assignment_id)
            assignments.append(assignment)
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
def _list_course_graded_submissions(token, course, graded_since, base_url, session):
    """Fetch all pages of work graded since a cutoff for one validated course."""
    next_url = f"{base_url}/api/v1/courses/{course['id']}/students/submissions"
    params = {
        "workflow_state": "graded",
        "include[]": "assignment",
        "per_page": 100,
        "graded_since": graded_since.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
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
            session,
        )
        normalized = (_normalize_submission(submission, course["name"]) for submission in page)
        submissions.extend(grade for grade in normalized if grade is not None)
        params = None
    return submissions


@sensitive_variables("token")
def list_graded_submissions(token, courses, graded_since, session=None):
    """Return the student's published submissions graded since a cutoff across the courses."""
    base_url = canvas_base_url()
    for course in courses:
        _validate_assignment_course(course)
    with ThreadPoolExecutor(MAX_CONCURRENT_REQUESTS) as pool:
        pages = pool.map(
            partial(_list_course_graded_submissions, token, base_url=base_url, session=session),
            courses,
            [graded_since] * len(courses),
        )
        return [submission for page in pages for submission in page]
