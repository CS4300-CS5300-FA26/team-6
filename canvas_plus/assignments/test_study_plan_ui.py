"""Request tests for generating a study plan from selected assignments."""

from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse
from django.utils import timezone
import pytest

from assignments.models import Assignment
from study_plan.models import StudyPlan, StudySession


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
        )

    selected_assignments = [
        make_assignment(101, "Selected lab report"),
        make_assignment(102, "Selected reading response"),
    ]
    unselected_assignment = make_assignment(103, "Unselected worksheet")
    plan = StudyPlan.objects.create(
        user=user,
        notices=["Some selected work could not be scheduled."],
    )
    start = timezone.now() + timedelta(days=1)
    for offset, assignment in enumerate(selected_assignments):
        session_start = start + timedelta(hours=offset)
        StudySession.objects.create(
            plan=plan,
            assignment=assignment,
            start=session_start,
            end=session_start + timedelta(minutes=30),
        )

    selected_ids = [assignment.pk for assignment in selected_assignments]
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

    study_plan_response = client.get(reverse("availability:list"))
    assert selected_assignments[0].title in study_plan_response.content.decode()
    assert selected_assignments[1].title in study_plan_response.content.decode()
    assert plan.notices[0] in study_plan_response.content.decode()
    assert unselected_assignment.title not in study_plan_response.content.decode()