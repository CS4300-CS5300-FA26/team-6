"""Request tests for generating a study plan from selected assignments."""

from datetime import date, datetime, time, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup
from cryptography.fernet import Fernet
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import Client
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
import pytest

from accounts.canvas_client import CanvasAPIError
from accounts.models import CanvasConnection
from assignments.models import Assignment
from assignments.sync import sync_canvas_assignments
from availability.models import Availability
from study_plan.models import StudyPlan, StudySession
from study_plan.exceptions import (
    EmptyAssignmentSelectionError,
    InaccessibleAssignmentError,
    NoEligibleAssignmentsError,
    NoUsableAvailabilityError,
    StudyPlanRetriesExhaustedError,
)


def assignment_row_titles(response, titles):
    """Return known titles rendered in assignment-table body rows."""
    soup = BeautifulSoup(response.content, "html.parser")
    rows = soup.select("table tbody tr")
    return {
        title
        for title in titles
        if any(title in row.get_text(" ", strip=True) for row in rows)
    }


def study_session_titles(response):
    """Return titles from the existing study-session section only."""
    soup = BeautifulSoup(response.content, "html.parser")
    return {
        title.get_text(" ", strip=True)
        for title in soup.select(".study-session .assignment-title")
    }


@pytest.mark.django_db
def test_generate_selected_assignments():
    """The submitted selection is passed to generation and appears in the plan."""
    user = get_user_model().objects.create_user(username="plan-ui-student")
    client = Client()
    client.force_login(user)

    def make_assignment(canvas_assignment_id, title):
        """Create one local assignment owned by the signed-in student."""
        return Assignment.objects.create(
            user=user,
            canvas_course_id=11,
            canvas_assignment_id=canvas_assignment_id,
            title=title,
            course="Biology",
            due_date=timezone.make_aware(
                datetime.combine(timezone.localdate() + timedelta(days=3), time(17))
            ),
        )

    selected_assignments = [
        make_assignment(101, "Selected lab report"),
        make_assignment(102, "Selected reading response"),
    ]
    unselected_assignment = make_assignment(103, "Unselected worksheet")
    available_date = timezone.localdate() + timedelta(days=1)
    Availability.objects.create(
        user=user,
        date=available_date,
        start_time=time(9),
        end_time=time(12),
    )
    plan = StudyPlan.objects.create(
        user=user,
    )
    start = timezone.make_aware(datetime.combine(available_date, time(9)))
    for offset, assignment in enumerate(selected_assignments):
        session_start = start + timedelta(hours=offset)
        StudySession.objects.create(
            plan=plan,
            assignment=assignment,
            start=session_start,
            end=session_start + timedelta(minutes=30),
        )

    selected_ids = [assignment.pk for assignment in selected_assignments]
    selection_page = client.get(reverse("availability:list"))
    assert selection_page.status_code == 200
    all_titles = [
        assignment.title
        for assignment in (*selected_assignments, unselected_assignment)
    ]

    with patch(
        "assignments.views.generate_plan",
        create=True,
        return_value=plan,
    ) as generate_plan:
        response = client.post(
            reverse("generate_plan"),
            {"assignment_ids": [str(assignment_id) for assignment_id in selected_ids]},
        )

    assert response.status_code == 302
    assert response["Location"] == reverse("availability:list")
    generate_plan.assert_called_once_with(user, selected_ids)

    assert assignment_row_titles(selection_page, all_titles) == set(all_titles)
    selection_soup = BeautifulSoup(selection_page.content, "html.parser")
    selection_form = next(
        (
            form
            for form in selection_soup.find_all("form")
            if form.select_one('input[name="assignment_ids"]')
        ),
        None,
    )
    assert selection_form is not None
    assert selection_form.find("button", {"type": "submit"}) is not None
    assert list(
        selection_page.context["availability_entries"].values_list("date", flat=True)
    ) == [available_date]

    study_plan_response = client.get(reverse("availability:list"))
    assert assignment_row_titles(study_plan_response, all_titles) == set(all_titles)
    assert study_session_titles(study_plan_response) == {
        selected_assignments[0].title,
        selected_assignments[1].title,
    }
    assert list(
        study_plan_response.context["availability_entries"].values_list("date", flat=True)
    ) == [available_date]


@pytest.mark.parametrize(
    ("failure", "error_type", "message"),
    [
        ("empty", EmptyAssignmentSelectionError, "Select at least one assignment."),
        (
            "inaccessible",
            InaccessibleAssignmentError,
            "One or more selected assignments are inaccessible.",
        ),
        (
            "ineligible",
            NoEligibleAssignmentsError,
            "No selected assignments are eligible to plan.",
        ),
        (
            "availability",
            NoUsableAvailabilityError,
            "No future unoccupied availability is available.",
        ),
        (
            "retries_exhausted",
            StudyPlanRetriesExhaustedError,
            "Could not generate a valid study plan after 2 attempts.",
        ),
    ],
)
@pytest.mark.django_db
def test_generation_failures(failure, error_type, message):
    """Planner failures are visible and never persist a new plan."""
    user = get_user_model().objects.create_user(username=f"plan-ui-{failure}")
    client = Client()
    client.force_login(user)
    assignment_ids = []

    if failure == "inaccessible":
        other_user = get_user_model().objects.create_user(
            username=f"plan-ui-other-{failure}"
        )
        assignment = Assignment.objects.create(
            user=other_user,
            canvas_course_id=11,
            canvas_assignment_id=201,
            title="Private assignment",
            course="Biology",
        )
        assignment_ids = [assignment.pk]
    elif failure != "empty":
        assignment = Assignment.objects.create(
            user=user,
            canvas_course_id=11,
            canvas_assignment_id=201,
            title="Selected assignment",
            course="Biology",
        )
        assignment_ids = [assignment.pk]

    with patch(
        "assignments.views.generate_plan",
        create=True,
        side_effect=error_type(message),
    ) as generate_plan:
        response = client.post(
            reverse("generate_plan"),
            {"assignment_ids": [str(assignment_id) for assignment_id in assignment_ids]},
            follow=True,
        )

    assert response.status_code == 200
    assert response.wsgi_request.path == reverse("availability:list")
    assert message in response.content.decode()
    assert "My Availability" in response.content.decode()
    assert StudyPlan.objects.filter(user=user).count() == 0
    generate_plan.assert_called_once_with(user, assignment_ids)


@pytest.mark.django_db
def test_generation_action_requires_login_post_and_csrf():
    """Only authenticated CSRF-protected POST requests can start generation."""
    url = reverse("generate_plan")
    user = get_user_model().objects.create_user(username="plan-ui-protected-action")

    anonymous_response = Client().post(url, {"assignment_ids": []})
    assert anonymous_response.status_code == 302
    assert anonymous_response.url.startswith(reverse("login"))

    client = Client()
    client.force_login(user)
    assert client.get(url).status_code == 405

    csrf_checked_client = Client(enforce_csrf_checks=True)
    csrf_checked_client.force_login(user)
    assert csrf_checked_client.post(url, {"assignment_ids": []}).status_code == 403
    assert StudyPlan.objects.filter(user=user).count() == 0


@pytest.mark.django_db
def test_default_local_calendar_window():
    """The default filter includes the whole Denver day and next 13 dates."""
    user = get_user_model().objects.create_user(username="plan-ui-date-window")
    client = Client()
    client.force_login(user)
    local_timezone = ZoneInfo(settings.TIME_ZONE)
    today = date(2026, 3, 8)
    fixed_now = datetime.combine(today, time(12), tzinfo=local_timezone)
    due_dates = [
        datetime.combine(today, time(0, 1), tzinfo=local_timezone),
        datetime.combine(today, time.min, tzinfo=local_timezone),
        datetime.combine(today + timedelta(days=13), time.max, tzinfo=local_timezone),
        datetime.combine(today + timedelta(days=14), time.min, tzinfo=local_timezone),
        None,
    ]
    titles = [
        "Earlier today",
        "Start of today",
        "End of day 14",
        "Start of day 15",
        "No due date",
    ]
    for index, (title, due_date) in enumerate(zip(titles, due_dates), start=301):
        Assignment.objects.create(
            user=user,
            canvas_assignment_id=index,
            canvas_course_id=11,
            title=title,
            course="Biology",
            due_date=due_date,
            sync_state="synced",
        )
    available_date = today + timedelta(days=1)
    Availability.objects.create(
        user=user,
        date=available_date,
        start_time=time(9),
        end_time=time(10),
    )
    plan = StudyPlan.objects.create(user=user)
    session_assignment = Assignment.objects.create(
        user=user,
        canvas_assignment_id=306,
        canvas_course_id=11,
        title="Existing study session",
        course="Biology",
    )
    StudySession.objects.create(
        plan=plan,
        assignment=session_assignment,
        start=fixed_now + timedelta(days=1),
        end=fixed_now + timedelta(days=1, minutes=30),
    )

    with (
        patch("django.utils.timezone.now", return_value=fixed_now),
    ):
        response = client.get(reverse("availability:list"))

    assert response.status_code == 200
    assert "My Availability" in response.content.decode()
    assert "Existing study session" in response.content.decode()
    assert list(
        response.context["availability_entries"].values_list("date", flat=True)
    ) == [available_date]
    assert assignment_row_titles(response, titles) == set(titles[:3])


@pytest.mark.django_db
def test_assignment_search_and_filters():
    """Search and filters use the student's complete synced snapshot."""
    user = get_user_model().objects.create_user(username="plan-ui-search")
    client = Client()
    client.force_login(user)
    other_user = get_user_model().objects.create_user(username="plan-ui-search-other")
    local_timezone = ZoneInfo(settings.TIME_ZONE)
    fixed_now = datetime(2026, 11, 7, 10, tzinfo=local_timezone)
    courses = [
        {"id": 11, "name": "Mathematics"},
        {"id": 22, "name": "Biology"},
    ]
    snapshot = [
        {
            "canvas_assignment_id": 401,
            "canvas_course_id": 11,
            "title": "Algebra proof set",
            "course_name": "Mathematics",
            "due_date": datetime(2026, 11, 10, 17, tzinfo=local_timezone),
            "submitted": False,
            "description": "Prove the assigned identities.",
        },
        {
            "canvas_assignment_id": 402,
            "canvas_course_id": 22,
            "title": "Biology lab report",
            "course_name": "Biology",
            "due_date": datetime(2026, 11, 11, 17, tzinfo=local_timezone),
            "submitted": False,
            "description": "Write up the lab results.",
        },
        {
            "canvas_assignment_id": 403,
            "canvas_course_id": 22,
            "title": "Biology field notes",
            "course_name": "Biology",
            "due_date": datetime(2026, 11, 12, 17, tzinfo=local_timezone),
            "submitted": False,
            "description": "Summarize field observations.",
        },
        {
            "canvas_assignment_id": 404,
            "canvas_course_id": 22,
            "title": "Undated lab reflection",
            "course_name": "Biology",
            "due_date": None,
            "submitted": False,
            "description": "Reflect on the lab.",
        },
    ]
    Assignment.objects.create(
        user=other_user,
        canvas_course_id=22,
        canvas_assignment_id=405,
        title="Biology private assignment",
        course="Biology",
        due_date=datetime(2026, 11, 11, 17, tzinfo=local_timezone),
    )
    titles = [item["title"] for item in snapshot]
    sync_canvas_assignments(user, courses, snapshot)
    connection_settings = override_settings(
        CANVAS_BASE_URL="https://canvas.example.edu",
        CANVAS_TOKEN_ENCRYPTION_KEY=Fernet.generate_key().decode(),
    )

    with connection_settings:
        connection = CanvasConnection(
            user=user,
            canvas_url="https://canvas.example.edu",
        )
        connection.set_token("fake-plan-ui-token")
        connection.save()
        upcoming = [item for item in snapshot if item["due_date"] is not None]
        with (
            patch("assignments.views.timezone.now", return_value=fixed_now),
            patch("assignments.views.list_courses", return_value=courses),
            patch("assignments.views.list_upcoming_assignments", return_value=upcoming),
            patch("assignments.views.list_graded_submissions", return_value=[]),
            patch("assignments.views.list_all_assignments", return_value=snapshot),
        ):
            url = reverse("availability:list")

            def rows(params):
                response = client.get(url, params)
                assert response.status_code == 200
                return assignment_row_titles(response, titles), response.content.decode()

            matching, _ = rows({"q": "proof"})
            assert matching == {"Algebra proof set"}

            matching, _ = rows({"q": "Biology"})
            assert matching == {
                "Biology lab report",
                "Biology field notes",
            }

            matching, _ = rows({"course": "Biology"})
            assert matching == {
                "Biology lab report",
                "Biology field notes",
            }
            assert "Biology private assignment" not in client.get(
                url, {"course": "Biology"}
            ).content.decode()

            matching, _ = rows(
                {
                    "q": "lab",
                    "course": "Biology",
                    "due_from": "2026-11-11",
                    "due_to": "2026-11-11",
                }
            )
            assert matching == {"Biology lab report"}

            matching, _ = rows({"due_from": "", "due_to": ""})
            assert matching == set(titles)

            matching, _ = rows({"no_due_date": "1"})
            assert matching == {"Undated lab reflection"}

            matching, empty_html = rows({"q": "no assignment has this title"})
            assert matching == set()
            assert "No assignments" in empty_html

            cache.clear()
            with patch(
                "assignments.views.list_courses",
                side_effect=CanvasAPIError("Canvas is temporarily unavailable."),
            ):
                unavailable = client.get(url)
            unavailable_html = unavailable.content.decode()
            assert unavailable.status_code == 200
            assert "Unable to load upcoming assignments" in unavailable_html
            assert "No assignments" not in unavailable_html