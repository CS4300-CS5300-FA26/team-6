"""Fake Canvas HTTP responses shared by Course Hub pytest and Behave tests."""

from copy import deepcopy
from datetime import timedelta
from unittest.mock import Mock, patch
from urllib.parse import urlparse

from bs4 import BeautifulSoup
from django.urls import reverse
from django.utils import timezone


# Each keyword represents a separate Canvas enrollment/term fixture condition.
# pylint: disable-next=too-many-arguments
def hub_course(course_id, code, name, *, ended=False, role="student", state="active"):
    """Make a Canvas course with a short code distinct from its full name."""
    return {
        "id": course_id,
        "course_code": code,
        "name": name,
        "term": {"end_at": (timezone.now() + timedelta(days=-30 if ended else 90)).isoformat()},
        "enrollments": [{"type": f"{role.title()}Enrollment", "enrollment_state": state}],
    }


def active_hub_courses():
    """Use nonsequential API IDs so positional links cannot accidentally pass."""
    return [
        hub_course(43009, "CS 4300", "Software Engineering"),
        hub_course(21507, "MATH 2150", "Discrete Mathematics"),
        hub_course(13103, "ENGL 1310", "Rhetoric and Writing"),
        hub_course(10105, "HIST 1010", "World History"),
    ]


def excluded_hub_courses():
    """Cover ended terms, inactive students, and active nonstudent enrollments."""
    return [
        hub_course(99001, "OLD 1000", "Ended Term", ended=True),
        hub_course(99002, "OLD 2000", "Concluded Enrollment", state="completed"),
        hub_course(99003, "OLD 3000", "Invited Enrollment", state="invited"),
        hub_course(99004, "OLD 4000", "Teacher Enrollment", role="teacher"),
    ]


def course_links(response, courses):
    """Find course navigation by destination without prescribing CSS or ARIA markup."""
    destinations = {reverse("course_detail", args=[course["id"]]) for course in courses}
    return [
        link for link in BeautifulSoup(response.content, "html.parser").select("main a[href]")
        if link["href"] in destinations
    ]


# A fake HTTP service needs only the requests-compatible get entry point.
# pylint: disable-next=too-few-public-methods
class HubCanvas:
    """Serve deterministic Canvas data, honoring its enrollment query filters."""

    def __init__(self, courses):
        self.courses = courses
        self.course_calls = 0
        self.assignments = {
            course["id"]: [{
                "id": course["id"] * 10,
                "name": f"Upcoming work for {course['course_code']}",
                "due_at": (timezone.now() + timedelta(days=2)).isoformat(),
                "submission": {"submitted_at": None, "workflow_state": "unsubmitted"},
            }]
            for course in courses
        }

    def get(self, url, **kwargs):
        """Implement the HTTP boundary for direct and session-backed Canvas requests."""
        parsed = urlparse(url)
        assert parsed.netloc == "canvas.example.edu", f"Unexpected Canvas host: {url}"
        params = kwargs.get("params") or {}
        parts = parsed.path.strip("/").split("/")
        if parts == ["api", "v1", "courses"]:
            self.course_calls += 1
            data = [
                course for course in self.courses
                if any(
                    (not params.get("enrollment_type")
                     or enrollment["type"] == f"{params['enrollment_type'].title()}Enrollment")
                    and (not params.get("enrollment_state")
                         or enrollment["enrollment_state"] == params["enrollment_state"])
                    for enrollment in course["enrollments"]
                )
            ]
        elif parts[:3] == ["api", "v1", "courses"] and len(parts) >= 4:
            course_id = int(parts[3])
            if len(parts) == 4:
                data = {"id": course_id, "syllabus_body": "<p>Course policies</p>"}
            elif parts[4:] == ["assignments"]:
                data = (
                    self.assignments.get(course_id, [])
                    if params.get("bucket") == "upcoming" else []
                )
            elif parts[4:] == ["students", "submissions"]:
                data = []
            else:
                raise AssertionError(f"Unexpected Canvas URL: {url}")
        else:
            raise AssertionError(f"Unexpected Canvas URL: {url}")
        response = Mock(status_code=200, links={})
        response.json.return_value = deepcopy(data)
        return response


def install_hub_canvas(add_cleanup, courses):
    """Replace both HTTP entry points; no test contacts a live Canvas server."""
    canvas = HubCanvas(courses)
    targets = (
        "accounts.canvas_client.requests.get",
        "accounts.canvas_client.requests.Session.get",
    )
    for target in targets:
        patcher = patch(target, side_effect=canvas.get)
        patcher.start()
        add_cleanup(patcher.stop)
    return canvas


def hub_cache_clock(add_cleanup):
    """Advance only Django's cache clock, leaving test-runner timing unaffected."""
    clock = Mock(return_value=2000000000)
    targets = ("django.core.cache.backends.base.time", "django.core.cache.backends.locmem.time")
    for target in targets:
        patcher = patch(target, Mock(time=clock))
        patcher.start()
        add_cleanup(patcher.stop)
    return clock
