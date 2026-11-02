"""Canvas HTTP boundary tests for graded submissions; no request reaches Canvas."""

import threading
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch

import pytest

from .canvas_client import CanvasAPIError, CanvasAuthenticationError, list_graded_submissions

COURSE = {"id": 7, "name": "Software Engineering"}
URL = "https://canvas.example.edu/api/v1/courses/7/students/submissions"
SINCE = datetime(2026, 10, 16, 9, 30, tzinfo=timezone(timedelta(hours=-6)))


@pytest.fixture(autouse=True)
def canvas_settings(settings):
    """Use a fixed, non-secret Canvas origin."""
    settings.CANVAS_BASE_URL = "https://canvas.example.edu"


@pytest.fixture(autouse=True)
def sequential_canvas_requests(monkeypatch):
    """One worker keeps mocked responses in call order; concurrency tests opt back in."""
    monkeypatch.setattr("accounts.canvas_client.MAX_CONCURRENT_REQUESTS", 1)


def response(payload, *, status=200, next_url=None):
    """A requests-like response with pagination links."""
    result = Mock(status_code=status)
    result.json.return_value = payload
    result.links = {"next": {"url": next_url}} if next_url else {}
    return result


def submission(**overrides):
    """One graded submission as Canvas returns it, with include[]=assignment."""
    data = {
        "assignment": {"id": 23, "name": "Sprint 1 Retrospective"},
        "score": 92.0,
        "graded_at": "2026-10-20T15:05:34Z",
        "posted_at": "2026-10-20T15:10:00Z",
        "excused": False,
    }
    return {**data, **overrides}


def titles(result):
    """The assignment names, in the order returned."""
    return [grade["assignment"] for grade in result]


@pytest.mark.unit
def test_graded_submission_is_normalized():
    """Canvas JSON becomes the plain dict the dashboard expects."""
    with patch("accounts.canvas_client.requests.get", return_value=response([submission()])):
        result = list_graded_submissions("fake-token", [COURSE], SINCE)
    assert result == [{
        "assignment": "Sprint 1 Retrospective",
        "course": "Software Engineering",
        "score": 92.0,
        "graded_at": datetime(2026, 10, 20, 15, 5, 34, tzinfo=timezone.utc),
    }]


@pytest.mark.unit
def test_request_asks_for_the_students_graded_work_with_assignment_names():
    """One authenticated request per course, filtered to graded work for the token's owner."""
    with patch("accounts.canvas_client.requests.get", return_value=response([])) as get:
        list_graded_submissions("fake-token", [COURSE], SINCE)
    assert get.call_args.args == (URL,)
    params = get.call_args.kwargs["params"]
    assert params["workflow_state"] == "graded"
    assert params["include[]"] == "assignment"
    assert params["per_page"] == 100
    assert params["graded_since"] == "2026-10-16T15:30:00Z"
    assert "student_ids[]" not in params
    assert get.call_args.kwargs["headers"]["Authorization"] == "Bearer fake-token"


@pytest.mark.unit
def test_every_page_is_returned_and_next_page_keeps_its_own_query():
    """Both pages come back, and the next link is followed with params=None."""
    next_url = f"{URL}?page=2&opaque=next"
    with patch("accounts.canvas_client.requests.get", side_effect=[
        response([submission(assignment={"id": 1, "name": "First"})], next_url=next_url),
        response([submission(assignment={"id": 2, "name": "Second"})]),
    ]) as get:
        result = list_graded_submissions("fake-token", [COURSE], SINCE)
    assert titles(result) == ["First", "Second"]
    assert get.call_args_list[1].args == (next_url,)
    assert get.call_args_list[1].kwargs["params"] is None


@pytest.mark.unit
def test_submissions_from_several_courses_carry_their_course_name():
    """Each course is requested, and each result names the course it came from."""
    courses = [COURSE, {"id": 8, "name": "Databases"}]
    with patch("accounts.canvas_client.requests.get", side_effect=[
        response([submission(assignment={"id": 1, "name": "Sprint 1"})]),
        response([submission(assignment={"id": 2, "name": "ER Diagram"})]),
    ]):
        result = list_graded_submissions("fake-token", courses, SINCE)
    assert {(grade["assignment"], grade["course"]) for grade in result} == {
        ("Sprint 1", "Software Engineering"),
        ("ER Diagram", "Databases"),
    }


@pytest.mark.unit
def test_no_courses_means_no_requests():
    """Without enrolled courses there is nothing to ask Canvas for."""
    with patch("accounts.canvas_client.requests.get") as get:
        assert list_graded_submissions("fake-token", [], SINCE) == []  # pylint: disable=use-implicit-booleaness-not-comparison  # Compare to [] on purpose: the contract is an empty list
    get.assert_not_called()


@pytest.mark.unit
def test_null_score_is_kept_as_none():
    """An unscored submission passes through; recent_grades decides to drop it."""
    with patch("accounts.canvas_client.requests.get",
               return_value=response([submission(score=None)])):
        result = list_graded_submissions("fake-token", [COURSE], SINCE)
    assert result[0]["score"] is None


@pytest.mark.unit
@pytest.mark.parametrize("overrides", [
    {"excused": True},
    {"posted_at": None},
    {"graded_at": None},
], ids=["excused", "not-posted", "never-graded"])
def test_submissions_with_no_published_grade_are_skipped(overrides):
    """Excused, unposted, or ungraded work is not a published score."""
    with patch("accounts.canvas_client.requests.get",
               return_value=response([submission(**overrides)])):
        assert list_graded_submissions("fake-token", [COURSE], SINCE) == []  # pylint: disable=use-implicit-booleaness-not-comparison  # Compare to [] on purpose: the contract is an empty list


@pytest.mark.unit
def test_rejected_token_raises_authentication_error():
    """A 401 means the saved token no longer works."""
    with patch("accounts.canvas_client.requests.get", return_value=response([], status=401)):
        with pytest.raises(CanvasAuthenticationError):
            list_graded_submissions("fake-token", [COURSE], SINCE)


@pytest.mark.unit
@pytest.mark.parametrize("status", [403, 429, 500])
def test_other_http_failures_are_not_expired_tokens(status):
    """Only a 401 means the token is bad; anything else is a temporary Canvas problem."""
    with patch("accounts.canvas_client.requests.get",
               return_value=response([], status=status)):
        with pytest.raises(CanvasAPIError) as raised:
            list_graded_submissions("fake-token", [COURSE], SINCE)
    assert not isinstance(raised.value, CanvasAuthenticationError)


def without_assignment():
    """A submission whose assignment object Canvas left out."""
    data = submission()
    del data["assignment"]
    return data


@pytest.mark.unit
@pytest.mark.parametrize("payload", [
    "not a submission",
    without_assignment(),
    submission(assignment={"id": 23, "name": 5}),
    submission(score="A"),
    submission(score=True),
    submission(graded_at="yesterday"),
], ids=["not-a-dict", "missing-assignment", "name-not-text", "score-not-number",
        "score-is-bool", "unparseable-date"])
def test_malformed_submission_raises_api_error(payload):
    """Unexpected Canvas data is an error, never a wrong grade on the dashboard."""
    with patch("accounts.canvas_client.requests.get", return_value=response([payload])):
        with pytest.raises(CanvasAPIError):
            list_graded_submissions("fake-token", [COURSE], SINCE)


@pytest.mark.unit
def test_requests_reuse_the_supplied_session():
    """Graded work is fetched through the caller's session instead of a new connection."""
    session = Mock()
    session.get.return_value = response([submission()])
    with patch("accounts.canvas_client.requests.get") as get:
        result = list_graded_submissions("fake-token", [COURSE], SINCE, session=session)

    get.assert_not_called()
    assert titles(result) == ["Sprint 1 Retrospective"]


@pytest.mark.unit
def test_course_requests_run_concurrently(monkeypatch):
    """Every course's graded work is requested at once instead of one at a time."""
    monkeypatch.undo()  # opt back in to real concurrency
    courses = [COURSE, {"id": 8, "name": "Databases"}]
    all_in_flight = threading.Barrier(2, timeout=2)

    def get(*_args, **_kwargs):
        all_in_flight.wait()  # breaks, failing the test, if requests run sequentially
        return response([])

    with patch("accounts.canvas_client.requests.get", side_effect=get):
        assert not list_graded_submissions("fake-token", courses, SINCE)
