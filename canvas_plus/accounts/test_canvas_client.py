"""Canvas HTTP boundary tests; no requests reach a real Canvas server."""

from datetime import datetime, timezone
from unittest.mock import Mock, patch

import pytest
import requests

from .canvas_client import (
    CanvasAPIError,
    CanvasAuthenticationError,
    list_courses,
    list_upcoming_assignments,
)


@pytest.fixture(autouse=True)
def canvas_settings(settings):
    """Use a fixed, non-secret Canvas origin."""
    settings.CANVAS_BASE_URL = "https://canvas.example.edu/"


def response(courses, *, status=200, next_url=None):
    """Construct a requests-like response, including its pagination links."""
    result = Mock(status_code=status)
    result.json.return_value = courses
    result.links = {"next": {"url": next_url}} if next_url else {}
    return result


@pytest.mark.unit
def test_courses_include_every_page_and_authenticate_each_request():
    """Given two pages, return both and preserve the opaque next-page query."""
    next_url = "https://canvas.example.edu/api/v1/courses?opaque=next"
    with patch("accounts.canvas_client.requests.get", side_effect=[
        response([{"id": 1, "name": "First"}], next_url=next_url),
        response([{"id": 2, "name": "Second"}]),
    ]) as get:
        assert [course["name"] for course in list_courses("fake-token")] == ["First", "Second"]
    assert get.call_count == 2
    assert get.call_args_list[1].args == (next_url,)
    assert get.call_args_list[0].kwargs["params"]["enrollment_state"] == "active"
    assert get.call_args_list[0].kwargs["params"]["per_page"] == 100
    assert get.call_args_list[1].kwargs["params"] is None
    for call in get.call_args_list:
        assert call.kwargs["headers"]["Authorization"] == "Bearer fake-token"
        assert call.kwargs["timeout"] == 10
        assert call.kwargs["allow_redirects"] is False


@pytest.mark.unit
@pytest.mark.parametrize("next_url", [
    "https://untrusted.example/api/v1/courses",
    "http://canvas.example.edu/api/v1/courses",
    "https://user:password@canvas.example.edu/api/v1/courses",
])
def test_pagination_does_not_send_credentials_to_another_origin(next_url):
    """A pagination link must never leak the bearer token to another origin."""
    with patch(
        "accounts.canvas_client.requests.get", return_value=response([], next_url=next_url)
    ) as get:
        with pytest.raises(CanvasAPIError):
            list_courses("fake-token")
    assert get.call_count == 1


@pytest.mark.unit
def test_repeated_pagination_link_stops_instead_of_looping():
    """A repeated next link must not hang the web request indefinitely."""
    url = "https://canvas.example.edu/api/v1/courses"
    with patch(
        "accounts.canvas_client.requests.get", return_value=response([], next_url=url)
    ) as get:
        with pytest.raises(CanvasAPIError):
            list_courses("fake-token")
    assert get.call_count == 1


@pytest.mark.unit
@pytest.mark.parametrize("status", [302, 403, 429, 500])
def test_other_http_failures_are_not_invalid_tokens(status):
    """Redirects, permissions, throttling, and outages have a separate outcome."""
    with patch("accounts.canvas_client.requests.get", return_value=response({}, status=status)):
        with pytest.raises(CanvasAPIError):
            list_courses("fake-token")


@pytest.mark.unit
def test_rejected_credentials_on_a_later_page_expire_the_connection():
    """Authentication must be checked for every page, not just the first."""
    with patch("accounts.canvas_client.requests.get", side_effect=[
        response([], next_url="https://canvas.example.edu/api/v1/courses?page=2"),
        response({}, status=401),
    ]):
        with pytest.raises(CanvasAuthenticationError):
            list_courses("fake-token")


@pytest.mark.unit
@pytest.mark.parametrize("error", [requests.Timeout, requests.ConnectionError])
def test_network_failures_have_a_safe_error(error):
    """Network exceptions are translated without exposing request credentials."""
    with patch("accounts.canvas_client.requests.get", side_effect=error("fake-token")):
        with pytest.raises(CanvasAPIError) as caught:
            list_courses("fake-token")
    assert "fake-token" not in str(caught.value)


@pytest.mark.unit
@pytest.mark.parametrize("payload", [{"error": "not a list"}, ["not a course"], [{"id": 1}]])
def test_malformed_course_data_is_not_treated_as_success(payload):
    """Unexpected JSON shapes cannot silently become course names."""
    with patch("accounts.canvas_client.requests.get", return_value=response(payload)):
        with pytest.raises(CanvasAPIError):
            list_courses("fake-token")


@pytest.mark.unit
def test_upcoming_assignments_are_normalized_and_include_course_name():
    """Return upcoming assignments with a UTC due date and their course name."""
    courses = [{"id": 42, "name": "CS 4300"}]
    assignments = [{
        "name": "Project 1",
        "due_at": "2026-10-22T18:30:00-06:00",
    }]
    with patch(
        "accounts.canvas_client.requests.get",
        side_effect=[response(assignments), response([])],
    ) as get:
        result = list_upcoming_assignments("fake-token", courses)

    assert result == [{
        "title": "Project 1",
        "course_name": "CS 4300",
        "due_date": datetime(2026, 10, 23, 0, 30, tzinfo=timezone.utc),
        "submitted": False,
    }]
    assert get.call_args_list[0].args == (
        "https://canvas.example.edu/api/v1/courses/42/assignments",
    )
    assert get.call_args_list[0].kwargs["params"] == {
        "bucket": "upcoming", "include[]": "submission", "per_page": 100,
    }
    assert get.call_args_list[1].kwargs["params"] == {
        "bucket": "overdue", "include[]": "submission", "per_page": 100,
    }
    for call in get.call_args_list:
        assert call.kwargs["headers"]["Authorization"] == "Bearer fake-token"


@pytest.mark.unit
def test_upcoming_assignments_preserve_missing_due_date_as_none():
    """A Canvas null due_at value remains None in the normalized record."""
    courses = [{"id": 42, "name": "CS 4300"}]
    with patch(
        "accounts.canvas_client.requests.get",
        side_effect=[
            response([{"name": "Project 1", "due_at": None}]),
            response([]),
        ],
    ):
        result = list_upcoming_assignments("fake-token", courses)

    assert result == [{
        "title": "Project 1",
        "course_name": "CS 4300",
        "due_date": None,
        "submitted": False,
    }]


@pytest.mark.unit
@pytest.mark.parametrize(("due_at", "message"), [
    ("not-a-date", "invalid assignment due date"),
    ("2026-10-22T18:30:00", "invalid assignment due date"),
    (123, "unexpected assignment data"),
    (True, "unexpected assignment data"),
])
def test_upcoming_assignments_reject_malformed_due_dates(due_at, message):
    """Malformed or timezone-naive due_at values cannot enter normalized data."""
    courses = [{"id": 42, "name": "CS 4300"}]
    with patch(
        "accounts.canvas_client.requests.get",
        return_value=response([{"name": "Project 1", "due_at": due_at}]),
    ):
        with pytest.raises(CanvasAPIError, match=message):
            list_upcoming_assignments("fake-token", courses)


@pytest.mark.unit
@pytest.mark.parametrize("course", [
    "not a course",
    {},
    {"id": True, "name": "CS 4300"},
    {"id": "42", "name": "CS 4300"},
    {"id": 0, "name": "CS 4300"},
    {"id": -1, "name": "CS 4300"},
    {"id": 42, "name": None},
    {"id": 42, "name": 4300},
])
def test_upcoming_assignments_reject_invalid_course_records_before_request(course):
    """Invalid course records fail before their data can form a request URL."""
    with patch("accounts.canvas_client.requests.get") as get:
        with pytest.raises(CanvasAPIError):
            list_upcoming_assignments("fake-token", [course])

    get.assert_not_called()


@pytest.mark.unit
def test_upcoming_assignments_are_sorted_by_due_date_across_courses():
    """Assignments sort by due date, with assignments lacking dates last."""
    courses = [
        {"id": 42, "name": "CS 4300"},
        {"id": 84, "name": "MATH 2250"},
    ]
    responses = [
        response([
            {"name": "Later", "due_at": "2026-10-24T18:30:00Z"},
            {"name": "No due date", "due_at": None},
        ]),
        response([]),
        response([{"name": "Earlier", "due_at": "2026-10-23T18:30:00Z"}]),
        response([]),
    ]
    with patch("accounts.canvas_client.requests.get", side_effect=responses):
        result = list_upcoming_assignments("fake-token", courses)

    assert [assignment["title"] for assignment in result] == [
        "Earlier",
        "Later",
        "No due date",
    ]


@pytest.mark.unit
def test_multiple_undated_assignments_sort_after_dated_in_original_order():
    """Several null due dates are not compared and keep their original order."""
    courses = [
        {"id": 42, "name": "CS 4300"},
        {"id": 84, "name": "MATH 2250"},
    ]
    responses = [
        response([
            {"name": "Undated A", "due_at": None},
            {"name": "Later", "due_at": "2026-10-24T18:30:00Z"},
            {"name": "Undated B", "due_at": None},
        ]),
        response([]),
        response([
            {"name": "Undated C", "due_at": None},
            {"name": "Earlier", "due_at": "2026-10-23T18:30:00Z"},
        ]),
        response([]),
    ]
    with patch("accounts.canvas_client.requests.get", side_effect=responses):
        result = list_upcoming_assignments("fake-token", courses)

    assert [assignment["title"] for assignment in result] == [
        "Earlier",
        "Later",
        "Undated A",
        "Undated B",
        "Undated C",
    ]


@pytest.mark.unit
def test_only_undated_assignments_keep_original_order():
    """A result set with no due dates at all sorts without error."""
    courses = [{"id": 42, "name": "CS 4300"}]
    payload = [{"name": "First", "due_at": None}, {"name": "Second", "due_at": None}]
    with patch(
        "accounts.canvas_client.requests.get",
        side_effect=[response(payload), response([])],
    ):
        result = list_upcoming_assignments("fake-token", courses)

    assert [assignment["title"] for assignment in result] == ["First", "Second"]


@pytest.mark.unit
def test_upcoming_assignments_combine_course_results_and_return_empty_list():
    """Each supplied course is queried and a successful empty response is empty."""
    courses = [
        {"id": 42, "name": "CS 4300"},
        {"id": 84, "name": "MATH 2250"},
    ]
    with patch(
        "accounts.canvas_client.requests.get",
        side_effect=[response([]), response([]), response([]), response([])],
    ) as get:
        result = list_upcoming_assignments("fake-token", courses)

    assert not result
    assert get.call_count == 4
    assert [call.kwargs["params"] for call in get.call_args_list] == [
        {"bucket": "upcoming", "include[]": "submission", "per_page": 100},
        {"bucket": "overdue", "include[]": "submission", "per_page": 100},
        {"bucket": "upcoming", "include[]": "submission", "per_page": 100},
        {"bucket": "overdue", "include[]": "submission", "per_page": 100},
    ]


@pytest.mark.unit
def test_upcoming_assignments_follow_pagination_without_repeating_query_params():
    """Follow Canvas next links and retain the course name across pages."""
    courses = [{"id": 42, "name": "CS 4300"}]
    next_url = "https://canvas.example.edu/api/v1/courses/42/assignments?page=2"
    with patch(
        "accounts.canvas_client.requests.get",
        side_effect=[
            response([{"name": "Project 1", "due_at": None}], next_url=next_url),
            response([{"name": "Project 2", "due_at": None}]),
            response([]),
        ],
    ) as get:
        result = list_upcoming_assignments("fake-token", courses)

    assert [assignment["title"] for assignment in result] == ["Project 1", "Project 2"]
    assert get.call_args_list[1].args == (next_url,)
    assert get.call_args_list[0].kwargs["params"] == {
        "bucket": "upcoming", "include[]": "submission", "per_page": 100,
    }
    assert get.call_args_list[1].kwargs["params"] is None
    assert get.call_args_list[2].kwargs["params"] == {
        "bucket": "overdue", "include[]": "submission", "per_page": 100,
    }
    for call in get.call_args_list:
        assert call.kwargs["headers"]["Authorization"] == "Bearer fake-token"
        assert call.kwargs["timeout"] == 10
        assert call.kwargs["allow_redirects"] is False


@pytest.mark.unit
def test_upcoming_assignments_reject_unauthorized_pagination_links():
    """Do not send the bearer token to a different origin from a next link."""
    courses = [{"id": 42, "name": "CS 4300"}]
    with patch(
        "accounts.canvas_client.requests.get",
        return_value=response(
            [], next_url="https://untrusted.example/api/v1/assignments"
        ),
    ) as get:
        with pytest.raises(CanvasAPIError):
            list_upcoming_assignments("fake-token", courses)

    assert get.call_count == 1


@pytest.mark.unit
def test_upcoming_assignments_raise_authentication_error_for_401():
    """A rejected token remains distinguishable from a transient Canvas failure."""
    courses = [{"id": 42, "name": "CS 4300"}]
    with patch(
        "accounts.canvas_client.requests.get",
        return_value=response({}, status=401),
    ):
        with pytest.raises(CanvasAuthenticationError):
            list_upcoming_assignments("fake-token", courses)


@pytest.mark.unit
@pytest.mark.parametrize("status", [403, 429, 500])
def test_upcoming_assignments_raise_api_error_for_other_http_failures(status):
    """Permission, throttling, and server errors are not treated as empty results."""
    courses = [{"id": 42, "name": "CS 4300"}]
    with patch(
        "accounts.canvas_client.requests.get",
        return_value=response({}, status=status),
    ):
        with pytest.raises(CanvasAPIError):
            list_upcoming_assignments("fake-token", courses)


@pytest.mark.unit
@pytest.mark.parametrize("payload", [
    {"error": "bad"},
    ["not an assignment"],
    [{}],
    [{"id": ["7"], "name": "x", "due_at": None}],
    [{"id": True, "name": "x", "due_at": None}],
])
def test_malformed_upcoming_assignment_data_raises_api_error(payload):
    """Malformed payloads cannot silently become assignment records."""
    courses = [{"id": 42, "name": "CS 4300"}]
    with patch(
        "accounts.canvas_client.requests.get",
        return_value=response(payload),
    ):
        with pytest.raises(CanvasAPIError):
            list_upcoming_assignments("fake-token", courses)


@pytest.mark.unit
def test_overdue_assignments_are_included_and_sorted_first():
    """Overdue work from the second bucket sorts ahead of upcoming work."""
    courses = [{"id": 42, "name": "CS 4300"}]
    with patch(
        "accounts.canvas_client.requests.get",
        side_effect=[
            response([{"name": "Soon", "due_at": "2026-10-23T18:30:00Z"}]),
            response([{"name": "Late", "due_at": "2026-10-20T18:30:00Z"}]),
        ],
    ):
        result = list_upcoming_assignments("fake-token", courses)

    assert [assignment["title"] for assignment in result] == ["Late", "Soon"]


@pytest.mark.unit
def test_assignment_returned_by_both_buckets_appears_once():
    """The same assignment id in both buckets yields a single card."""
    courses = [{"id": 42, "name": "CS 4300"}]
    with patch(
        "accounts.canvas_client.requests.get",
        side_effect=[
            response([{"id": 7, "name": "Race", "due_at": "2026-10-22T05:59:00Z"}]),
            response([{"id": 7, "name": "Race", "due_at": "2026-10-22T05:59:00Z"}]),
        ],
    ):
        result = list_upcoming_assignments("fake-token", courses)

    assert [assignment["title"] for assignment in result] == ["Race"]


@pytest.mark.unit
def test_distinct_assignment_ids_are_all_kept():
    """Different assignment ids from both buckets are all kept."""
    courses = [{"id": 42, "name": "CS 4300"}]
    with patch(
        "accounts.canvas_client.requests.get",
        side_effect=[
            response([{"id": 7, "name": "A", "due_at": "2026-10-22T05:59:00Z"}]),
            response([{"id": 8, "name": "B", "due_at": "2026-10-21T05:59:00Z"}]),
        ],
    ):
        result = list_upcoming_assignments("fake-token", courses)

    assert [assignment["title"] for assignment in result] == ["B", "A"]


ABSENT = object()


@pytest.mark.unit
@pytest.mark.parametrize("submission, submitted", [
    (ABSENT, False),
    (None, False),
    ({"workflow_state": "unsubmitted", "submitted_at": None}, False),
    ({"workflow_state": "unsubmitted", "submitted_at": None, "excused": False}, False),
    ({"workflow_state": "unsubmitted", "submitted_at": None, "excused": True}, True),
    ({"workflow_state": "submitted", "submitted_at": "2026-10-21T10:00:00Z"}, True),
    ({"workflow_state": "graded", "submitted_at": None}, True),
])
def test_submission_status_is_normalized(submission, submitted):
    """A missing, unsubmitted, submitted, or graded submission sets the flag."""
    courses = [{"id": 42, "name": "CS 4300"}]
    assignment = {"name": "Project 1", "due_at": None}
    if submission is not ABSENT:
        assignment["submission"] = submission
    with patch(
        "accounts.canvas_client.requests.get",
        side_effect=[response([assignment]), response([])],
    ):
        result = list_upcoming_assignments("fake-token", courses)

    assert result == [{
        "title": "Project 1",
        "course_name": "CS 4300",
        "due_date": None,
        "submitted": submitted,
    }]


@pytest.mark.unit
@pytest.mark.parametrize("submission", ["submitted", ["x"], 42])
def test_malformed_submission_raises_api_error(submission):
    """A submission that is neither absent, None, nor a dict is an error."""
    courses = [{"id": 42, "name": "CS 4300"}]
    with patch(
        "accounts.canvas_client.requests.get",
        return_value=response([
            {"name": "Project 1", "due_at": None, "submission": submission},
        ]),
    ):
        with pytest.raises(CanvasAPIError):
            list_upcoming_assignments("fake-token", courses)


@pytest.mark.unit
def test_overdue_request_failure_raises_api_error():
    """A failed overdue request surfaces as an error, not a partial list."""
    courses = [{"id": 42, "name": "CS 4300"}]
    with patch(
        "accounts.canvas_client.requests.get",
        side_effect=[response([]), response({}, status=500)],
    ):
        with pytest.raises(CanvasAPIError):
            list_upcoming_assignments("fake-token", courses)


@pytest.mark.unit
def test_overdue_request_rejected_token_raises_authentication_error():
    """A token rejected on the overdue call expires the connection."""
    courses = [{"id": 42, "name": "CS 4300"}]
    with patch(
        "accounts.canvas_client.requests.get",
        side_effect=[response([]), response({}, status=401)],
    ):
        with pytest.raises(CanvasAuthenticationError):
            list_upcoming_assignments("fake-token", courses)


@pytest.mark.unit
def test_overdue_pagination_rejects_other_origin():
    """A next link on the overdue bucket must stay on the Canvas origin."""
    courses = [{"id": 42, "name": "CS 4300"}]
    with patch(
        "accounts.canvas_client.requests.get",
        side_effect=[
            response([]),
            response([], next_url="https://untrusted.example/api/v1/assignments"),
        ],
    ) as get:
        with pytest.raises(CanvasAPIError):
            list_upcoming_assignments("fake-token", courses)

    assert get.call_count == 2


@pytest.mark.unit
def test_requests_reuse_the_supplied_session():
    """Courses and assignments share the caller's session instead of new connections."""
    session = Mock()
    session.get.side_effect = [
        response([{"id": 42, "name": "CS 4300"}]),
        response([]),
        response([]),
    ]
    with patch("accounts.canvas_client.requests.get") as get:
        courses = list_courses("fake-token", session=session)
        list_upcoming_assignments("fake-token", courses, session=session)

    get.assert_not_called()
    assert session.get.call_count == 3
