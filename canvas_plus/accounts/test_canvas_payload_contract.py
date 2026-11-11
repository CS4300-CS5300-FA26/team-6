"""Canvas JSON through the real client and student-facing pages (G4–G6, G9).

Shapes verified against the official Courses, Assignments and Submissions refs:
https://developerdocs.instructure.com/services/canvas/resources/courses
https://developerdocs.instructure.com/services/canvas/resources/assignments
https://developerdocs.instructure.com/services/canvas/resources/submissions
"""
# pylint: disable=import-error,redefined-outer-name
import json
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
import requests
from bs4 import BeautifulSoup
from cryptography.fernet import Fernet
from django.contrib.auth import get_user_model
from django.urls import reverse

from accounts.canvas_client import get_course_syllabus, list_graded_submissions
from accounts.models import CanvasConnection
from assignments.grades import recent_grades

NOW = datetime(2026, 11, 11, 12, tzinfo=timezone.utc)
COURSE = {"id": 42, "name": "Contract course"}
BASE_URL = "https://canvas.example.edu"


def canvas_response(payload):
    """Use requests' actual JSON decoder and Link-header behavior."""
    response = requests.Response()
    response.status_code = 200
    response.headers["Content-Type"] = "application/json"
    response._content = json.dumps(payload).encode()  # pylint: disable=protected-access
    return response


def submission(name, graded_at="2026-11-11T10:00:00Z", score=13.5):
    """A published Canvas submission with both grading-scheme and raw grades."""
    return {
        "assignment_id": 101,
        "workflow_state": "graded",
        "score": score,
        "grade": "B+",
        "graded_at": graded_at,
        "posted_at": "2026-11-11T11:00:00Z",
        "assignment": {"id": 101, "name": name, "points_possible": 20, "published": True},
    }


@pytest.fixture
def connected_student(client, settings):
    """A student using a real encrypted connection at a fixed time."""
    settings.CANVAS_BASE_URL = BASE_URL
    settings.CANVAS_TOKEN_ENCRYPTION_KEY = Fernet.generate_key().decode()
    user = get_user_model().objects.create_user(username="payload-student")
    connection = CanvasConnection(user=user, canvas_url=BASE_URL)
    connection.set_token("test-token")
    connection.save()
    client.force_login(user)
    with patch("django.utils.timezone.now", return_value=NOW):
        yield connection


@pytest.fixture
def canvas_http():
    """Route only HTTP; preserve real clients, normalization, views and templates."""
    data = {"detail": {"id": 42}, "assignments": [], "submissions": [], "calls": []}

    def get(url, **kwargs):
        params = kwargs.get("params") or {}
        data["calls"].append((url, params))
        if url == f"{BASE_URL}/api/v1/courses":
            payload = [COURSE]
        elif url == f"{BASE_URL}/api/v1/courses/42":
            payload = data["detail"]
        elif url == f"{BASE_URL}/api/v1/courses/42/assignments":
            payload = data["assignments"] if params["bucket"] == "overdue" else []
        elif url == f"{BASE_URL}/api/v1/courses/42/students/submissions":
            payload = data["submissions"]
            if data.get("filter_since"):
                cutoff = datetime.fromisoformat(params["graded_since"])
                payload = [
                    row for row in payload
                    if datetime.fromisoformat(row["graded_at"]) > cutoff
                ]
        else:
            raise AssertionError(f"Unexpected Canvas URL: {url}")
        return canvas_response(payload)

    with patch("requests.get", side_effect=get), patch("requests.Session.get", side_effect=get):
        yield data


@pytest.mark.django_db
@pytest.mark.parametrize("body", [{"syllabus_body": None}, {"syllabus_body": ""}, {}],
                         ids=["null", "empty", "omitted-characterization"])
def test_no_syllabus_in_course_detail_shows_no_syllabus_message(
    client, connected_student, canvas_http, body,
):
    """Given no syllabus, when detail is fetched with its include, then show no syllabus."""
    canvas_http["detail"] = {"id": 42, **body}
    syllabus = get_course_syllabus("test-token", 42)
    assert syllabus == body.get("syllabus_body")
    response = client.get(reverse("course_detail", args=[42]))
    assert response.status_code == 200
    assert b"No syllabus posted in Canvas for this course" in response.content
    detail_calls = [params for url, params in canvas_http["calls"] if url.endswith("/courses/42")]
    assert detail_calls == [{"include[]": "syllabus_body"}] * 2
    connected_student.refresh_from_db()
    assert connected_student.is_valid


@pytest.mark.django_db
def test_work_awaiting_review_is_submitted_without_past_due_badge(
    client, connected_student, canvas_http,
):
    """Given work awaiting review, when Canvas returns it, then show Submitted, not Past due."""
    canvas_http["assignments"] = [{
        "id": 101, "name": "Awaiting instructor review", "due_at": "2026-11-10T12:00:00Z",
        "submission": {"workflow_state": "pending_review", "submitted_at": "2026-11-09T12:00:00Z"},
    }]
    response = client.get(reverse("assignment_list"))
    assert response.status_code == 200
    assert response.context["assignments"][0]["submitted"] is True
    assert response.context["assignments"][0]["priority"] == "Submitted"
    soup = BeautifulSoup(response.content, "html.parser")
    assert soup.select_one(".assignment-status").get_text(strip=True) == "Submitted"
    assert not soup.select(".assignment-status--past-due")
    assert connected_student.is_valid


@pytest.mark.django_db
@pytest.mark.parametrize("score,display", [(13.5, "Score: 13.5"), (0, "Score: 0"), (None, None)],
                         ids=["numeric-score", "zero-score", "unscored"])
def test_published_work_displays_raw_score_and_omits_unscored_work(
    client, connected_student, canvas_http, score, display,
):
    """Given a letter grade and possible points, when displayed, then retain only the raw score."""
    canvas_http["submissions"] = [submission("Scored contract task", score=score)]
    response = client.get(reverse("assignment_list"))
    assert response.status_code == 200
    soup = BeautifulSoup(response.content, "html.parser")
    scores = [item.get_text(strip=True) for item in soup.select(".assignment-due")]
    assert scores == ([] if display is None else [display])
    assert (b"Scored contract task" in response.content) is (score is not None)
    assert b"B+" not in response.content
    assert b"%" not in response.content
    assert connected_student.is_valid


@pytest.mark.django_db
def test_recent_published_work_is_shown_newest_first_inside_the_window(
    client, connected_student, canvas_http,
):
    """Given work around the recent window, when fetched and displayed,
    then show recent work newest first.
    """
    canvas_http["submissions"] = [
        submission("Just inside", "2026-10-28T12:00:01Z"),
        submission("Just outside", "2026-10-28T11:59:59Z"),
        submission("Newest", "2026-11-11T11:00:00Z"),
    ]
    canvas_http["filter_since"] = True
    # A wider request demonstrates the raw outside timestamp is parsed too.
    # The page's request uses a server-filtered fixture, with no exact-boundary claim.
    grades = list_graded_submissions("test-token", [COURSE], NOW - timedelta(days=15))
    assert len(grades) == 3
    assert [grade["assignment"] for grade in recent_grades(grades, now=NOW)] == [
        "Newest", "Just inside",
    ]
    response = client.get(reverse("assignment_list"))
    assert response.status_code == 200
    assert [grade["assignment"] for grade in response.context["recently_graded"]] == [
        "Newest", "Just inside",
    ]
    html = response.content.decode()
    assert html.index("Newest") < html.index("Just inside")
    assert "Just outside" not in html
    submission_calls = [params for url, params in canvas_http["calls"]
                        if url.endswith("/students/submissions")]
    assert submission_calls[-1]["graded_since"] == "2026-10-28T12:00:00Z"
    assert connected_student.is_valid


@pytest.mark.django_db
def test_equivalent_offset_grading_times_represent_the_same_instant(
    connected_student, canvas_http,
):
    """Given equivalent offset grading times, when fetched,
    then normalize to the same UTC instant.
    """
    canvas_http["submissions"] = [
        submission("UTC", "2026-11-11T10:00:00Z"),
        submission("Offset", "2026-11-11T05:00:00-05:00"),
    ]
    grades = list_graded_submissions("test-token", [COURSE], NOW - timedelta(days=14))
    assert [grade["graded_at"] for grade in grades] == [
        datetime(2026, 11, 11, 10, tzinfo=timezone.utc),
        datetime(2026, 11, 11, 10, tzinfo=timezone.utc),
    ]
    assert all(grade["graded_at"].tzinfo is timezone.utc for grade in grades)
    assert connected_student.is_valid


@pytest.mark.django_db
def test_timezone_less_grading_time_shows_safe_unavailable_feedback(
    client, connected_student, canvas_http,
):
    """Given a grading time without a timezone, when fetched,
    then safely report unavailable grades.
    """
    canvas_http["submissions"] = [submission("Untrusted grading time", "2026-11-11T10:00:00")]
    response = client.get(reverse("assignment_list"))
    assert response.status_code == 200
    assert b"Unable to load recently graded work right now." in response.content
    assert b"Untrusted grading time" not in response.content
    assert b"No recently graded work" not in response.content
    connected_student.refresh_from_db()
    assert connected_student.is_valid
