"""Canvas HTTP boundary tests; no requests reach a real Canvas server."""

import threading
from datetime import datetime, timezone
from unittest.mock import Mock, patch

import pytest
import requests

from . import canvas_client
from .canvas_client import (
    CanvasAPIError,
    CanvasAuthenticationError,
    get_course_syllabus,
    list_courses,
    list_upcoming_assignments,
)


@pytest.fixture(autouse=True)
def canvas_settings(settings):
    """Use a fixed, non-secret Canvas origin."""
    settings.CANVAS_BASE_URL = "https://canvas.example.edu/"


@pytest.fixture(autouse=True)
def sequential_canvas_requests(monkeypatch):
    """One worker keeps mocked responses in call order; concurrency tests opt back in."""
    monkeypatch.setattr("accounts.canvas_client.MAX_CONCURRENT_REQUESTS", 1)


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
def test_course_list_request_includes_each_course_term():
    """Courses come back with their term so ended semesters can be hidden."""
    with patch("accounts.canvas_client.requests.get", return_value=response([])) as get:
        list_courses("fake-token")
    assert get.call_args.kwargs["params"]["include[]"] == "term"


@pytest.mark.unit
def test_course_syllabus_request_returns_syllabus_html():
    """The course request asks Canvas for the syllabus body and returns it."""
    with patch("accounts.canvas_client.requests.get",
               return_value=response({"id": 7, "syllabus_body": "<h4>Grading</h4>"})) as get:
        assert get_course_syllabus("fake-token", 7) == "<h4>Grading</h4>"
    assert get.call_args.args == ("https://canvas.example.edu/api/v1/courses/7",)
    assert get.call_args.kwargs["params"] == {"include[]": "syllabus_body"}


@pytest.mark.unit
def test_malformed_syllabus_is_not_treated_as_success():
    """A syllabus that isn't text or empty is reported as a Canvas problem, not shown."""
    with patch("accounts.canvas_client.requests.get",
               return_value=response({"id": 7, "syllabus_body": 42})):
        with pytest.raises(CanvasAPIError):
            get_course_syllabus("fake-token", 7)


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
        "id": 101,
        "name": "Project 1",
        "due_at": "2026-10-22T18:30:00-06:00",
    }]
    with patch(
        "accounts.canvas_client.requests.get",
        side_effect=[response(assignments), response([])],
    ) as get:
        result = list_upcoming_assignments("fake-token", courses)

    assert result == [{
        "canvas_assignment_id": 101,
        "canvas_course_id": 42,
        "title": "Project 1",
        "course_name": "CS 4300",
        "due_date": datetime(2026, 10, 23, 0, 30, tzinfo=timezone.utc),
        "submitted": False,
        "description": None,
        
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
            response([{"id": 101, "name": "Project 1", "due_at": None}]),
            response([]),
        ],
    ):
        result = list_upcoming_assignments("fake-token", courses)

    assert result == [{
        "canvas_assignment_id": 101,
        "canvas_course_id": 42,
        "title": "Project 1",
        "course_name": "CS 4300",
        "due_date": None,
        "submitted": False,
        "description": None,
        
    }]


@pytest.mark.unit
def test_all_assignments_across_courses_and_pages():
    """Fetch every assignment without bucket filtering and deduplicate by Canvas id."""
    operation = getattr(canvas_client, "list_all_assignments", None)
    assert callable(operation), "Canvas client has no all-assignment operation yet"

    courses = [
        {"id": 42, "name": "CS 4300"},
        {"id": 84, "name": "MATH 2250"},
    ]
    next_url = "https://canvas.example.edu/api/v1/courses/42/assignments?page=2"
    with patch(
        "accounts.canvas_client.requests.get",
        side_effect=[
            response([{
                "id": 101,
                "name": "Future project",
                "due_at": "2026-10-23T18:30:00Z",
                "description": "Project details",
            }], next_url=next_url),
            response([{
                "id": 102,
                "name": "Undated reading",
                "due_at": None,
                "description": "Read chapter 4",
            }]),
            response([
                {
                    "id": 101,
                    "name": "Duplicate project",
                    "due_at": "2026-10-23T18:30:00Z",
                    "description": "Duplicate record",
                },
                {
                    "id": 103,
                    "name": "Past quiz",
                    "due_at": "2026-10-01T18:30:00Z",
                    "description": None,
                },
            ]),
        ],
    ) as get:
        result = operation("fake-token", courses)

    assert result == [
        {
            "canvas_assignment_id": 101,
            "canvas_course_id": 42,
            "title": "Future project",
            "course_name": "CS 4300",
            "due_date": datetime(2026, 10, 23, 18, 30, tzinfo=timezone.utc),
            "submitted": False,
            "description": "Project details",
        },
        {
            "canvas_assignment_id": 102,
            "canvas_course_id": 42,
            "title": "Undated reading",
            "course_name": "CS 4300",
            "due_date": None,
            "submitted": False,
            "description": "Read chapter 4",
        },
        {
            "canvas_assignment_id": 103,
            "canvas_course_id": 84,
            "title": "Past quiz",
            "course_name": "MATH 2250",
            "due_date": datetime(2026, 10, 1, 18, 30, tzinfo=timezone.utc),
            "submitted": False,
            "description": None,
        },
    ]
    assert get.call_count == 3
    assert get.call_args_list[0].args == (
        "https://canvas.example.edu/api/v1/courses/42/assignments",
    )
    assert get.call_args_list[1].args == (next_url,)
    assert get.call_args_list[2].args == (
        "https://canvas.example.edu/api/v1/courses/84/assignments",
    )
    assert get.call_args_list[0].kwargs["params"] == {"per_page": 100}
    assert get.call_args_list[1].kwargs["params"] is None
    assert get.call_args_list[2].kwargs["params"] == {"per_page": 100}
    assert all(
        "bucket" not in call.kwargs["params"]
        for call in (get.call_args_list[0], get.call_args_list[2])
    )
    for call in get.call_args_list:
        assert call.kwargs["headers"]["Authorization"] == "Bearer fake-token"
        assert call.kwargs["timeout"] == 10
        assert call.kwargs["allow_redirects"] is False


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
        return_value=response([{"id": 113, "name": "Project 1", "due_at": due_at}]),
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
            {"id": 105, "name": "Later", "due_at": "2026-10-24T18:30:00Z"},
            {"id": 106, "name": "No due date", "due_at": None},
        ]),
        response([]),
        response([{"id": 107, "name": "Earlier", "due_at": "2026-10-23T18:30:00Z"}]),
        response([]),
    ]
    with patch("accounts.canvas_client.requests.get", side_effect=responses):
        result = list_upcoming_assignments("fake-token", courses)

    assert [
        (assignment["title"], assignment["canvas_assignment_id"], assignment["canvas_course_id"])
        for assignment in result
    ] == [
        ("Earlier", 107, 84),
        ("Later", 105, 42),
        ("No due date", 106, 42),
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
            {"id": 108, "name": "Undated A", "due_at": None},
            {"id": 109, "name": "Later", "due_at": "2026-10-24T18:30:00Z"},
            {"id": 110, "name": "Undated B", "due_at": None},
        ]),
        response([]),
        response([
            {"id": 111, "name": "Undated C", "due_at": None},
            {"id": 112, "name": "Earlier", "due_at": "2026-10-23T18:30:00Z"},
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
    payload = [
        {"id": 103, "name": "First", "due_at": None},
        {"id": 104, "name": "Second", "due_at": None},
    ]
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
            response([{"id": 116, "name": "Project 1", "due_at": None}], next_url=next_url),
            response([{"id": 117, "name": "Project 2", "due_at": None}]),
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

    assert get.call_count >= 1
    assert all(
        call.args[0].startswith("https://canvas.example.edu/") for call in get.call_args_list
    )


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
            response([{"id": 118, "name": "Soon", "due_at": "2026-10-23T18:30:00Z"}]),
            response([{"id": 119, "name": "Late", "due_at": "2026-10-20T18:30:00Z"}]),
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
    assignment = {"id": 101, "name": "Project 1", "due_at": None}
    if submission is not ABSENT:
        assignment["submission"] = submission
    with patch(
        "accounts.canvas_client.requests.get",
        side_effect=[response([assignment]), response([])],
    ):
        result = list_upcoming_assignments("fake-token", courses)

    assert result == [{
        "canvas_assignment_id": 101,
        "canvas_course_id": 42,
        "title": "Project 1",
        "course_name": "CS 4300",
        "due_date": None,
        "submitted": submitted,
        "description": None,
        
    }]


@pytest.mark.unit
@pytest.mark.parametrize("submission", ["submitted", ["x"], 42])
def test_malformed_submission_raises_api_error(submission):
    """A submission that is neither absent, None, nor a dict is an error."""
    courses = [{"id": 42, "name": "CS 4300"}]
    with patch(
        "accounts.canvas_client.requests.get",
        return_value=response([
            {"id": 114, "name": "Project 1", "due_at": None, "submission": submission},
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


@pytest.mark.unit
def test_course_requests_run_concurrently(monkeypatch):
    """Every course and bucket request is in flight at once instead of one at a time."""
    monkeypatch.undo()  # opt back in to real concurrency
    courses = [{"id": 42, "name": "CS 4300"}, {"id": 84, "name": "MATH 2250"}]
    all_in_flight = threading.Barrier(4, timeout=2)

    def get(*_args, **_kwargs):
        all_in_flight.wait()  # breaks, failing the test, if requests run sequentially
        return response([])

    with patch("accounts.canvas_client.requests.get", side_effect=get):
        assert not list_upcoming_assignments("fake-token", courses)


@pytest.mark.unit
def test_one_failing_course_fails_a_concurrent_load(monkeypatch):
    """A Canvas failure for one of several courses is an outage, not an expired token."""
    monkeypatch.undo()  # opt back in to real concurrency
    courses = [{"id": course_id, "name": f"Course {course_id}"} for course_id in (41, 42, 43)]

    def get(url, **_kwargs):
        return response({}, status=500) if "/courses/42/" in url else response([])

    with patch("accounts.canvas_client.requests.get", side_effect=get):
        with pytest.raises(CanvasAPIError) as error:
            list_upcoming_assignments("fake-token", courses)
    assert error.type is CanvasAPIError


@pytest.mark.unit
def test_rejected_token_during_a_concurrent_load(monkeypatch):
    """A revoked token is still reported as an authentication failure."""
    monkeypatch.undo()  # opt back in to real concurrency
    courses = [{"id": course_id, "name": f"Course {course_id}"} for course_id in (41, 42, 43)]
    with patch("accounts.canvas_client.requests.get", return_value=response({}, status=401)):
        with pytest.raises(CanvasAuthenticationError):
            list_upcoming_assignments("fake-token", courses)


@pytest.mark.unit
@pytest.mark.parametrize("identity", [{}, {"id": None}, {"id": True}, {"id": False},
                                      {"id": 0}, {"id": -1}])
def test_upcoming_assignments_require_positive_nonboolean_assignment_id(identity):
    """Missing, null, boolean, zero, and negative Canvas identities are unusable."""
    assignment = {"name": "Project 1", "due_at": None, **identity}
    with patch(
        "accounts.canvas_client.requests.get",
        side_effect=[response([assignment]), response([])],
    ):
        with pytest.raises(CanvasAPIError):
            list_upcoming_assignments("fake-token", [{"id": 42, "name": "CS 4300"}])
