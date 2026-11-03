"""Tests for AI-assisted assignment effort estimation."""

from datetime import datetime
from unittest.mock import patch
from django.contrib.auth import get_user_model
from django.utils import timezone
from assignments.models import Assignment

import pytest

from study_plan.effort_estimation import (
    estimate_and_save_assignment_effort,
    estimate_assignment_effort,
    has_enough_available_time,
    save_manual_effort_estimate,
)
from study_plan.schema import EffortEstimate


@pytest.mark.unit
def test_complete_assignment_receives_ai_effort_estimate():
    """Complete assignment information should be sent for AI inference."""

    # Create the structured response we expect the shared AI layer to return.
    fake_estimate = EffortEstimate(
        estimated_minutes=90,
        reason="The assignment requires research and written analysis.",
    )

    # Mock infer so this unit test never makes a real API request.
    with patch(
        "study_plan.effort_estimation.infer",
        return_value=fake_estimate,
    ) as mock_infer:
        estimate = estimate_assignment_effort(
            title="Research Paper",
            due_date=datetime(2026, 11, 10, 23, 59),
            assignment_information=(
                "Write a five-page research paper with at least "
                "five academic sources."
            ),
        )

    # Confirm the structured estimate is returned.
    assert estimate == fake_estimate
    assert estimate.estimated_minutes == 90

    # Confirm the shared inference layer was actually used.
    mock_infer.assert_called_once()


@pytest.mark.unit
@pytest.mark.parametrize(
    "title,due_date,assignment_information",
    [
        ("", datetime(2026, 11, 10, 23, 59), "Write a paper."),
        ("Research Paper", None, "Write a paper."),
        ("Research Paper", datetime(2026, 11, 10, 23, 59), ""),
    ],
)
def test_missing_information_requires_manual_estimate(
    title,
    due_date,
    assignment_information,
    ):
    """Incomplete assignment information should not call AI inference."""

    # Patch infer so we can prove that missing data stops before API use.
    with patch("study_plan.effort_estimation.infer") as mock_infer:
        estimate = estimate_assignment_effort(
            title=title,
            due_date=due_date,
            assignment_information=assignment_information,
        )

    # None tells the future UI to request a manual estimate.
    assert estimate is None

    # AI should not be called when required information is missing.
    mock_infer.assert_not_called()


@pytest.mark.unit
def test_available_time_can_cover_estimated_effort():
    """Enough study time should satisfy the estimated workload."""

    assert has_enough_available_time(
        estimated_minutes=90,
        available_minutes=120,
    )


@pytest.mark.unit
def test_estimate_exceeding_available_time_is_detected():
    """Insufficient study time should be detected."""

    assert not has_enough_available_time(
        estimated_minutes=180,
        available_minutes=120,
    )

@pytest.mark.django_db
def test_ai_effort_estimate_is_saved_to_assignment():
    """An AI-generated estimate should be persisted on the assignment."""

    # Create a student who owns the local Assignment record.
    user = get_user_model().objects.create_user(
        username="effort-student",
        password="test-password-123",
    )

    # Create a user-owned Canvas assignment using the new shared model.
    assignment = Assignment.objects.create(
        user=user,
        canvas_course_id=1001,
        canvas_assignment_id=2001,
        title="Research Paper",
        course="CS4300",
        due_date=timezone.now(),
    )

    # Create the structured AI result that the shared inference layer would normally return.
    fake_estimate = EffortEstimate(
        estimated_minutes=90,
        reason="The assignment requires research, drafting, and revision.",
    )

    # Mock AI inference so the test remains deterministic and does not make a real provider request.
    with patch(
        "study_plan.effort_estimation.infer",
        return_value=fake_estimate,
        ):
        result = estimate_and_save_assignment_effort(
            assignment=assignment,
            assignment_information=(
                "Write a five-page research paper using at least "
                "five academic sources."
            ),
        )

    # Reload the Assignment from the database so this test verifies actual persistence rather than only Python attributes.
    assignment.refresh_from_db()

    # Confirm the AI result was returned.
    assert result == fake_estimate

    # Confirm the estimate was persisted in minutes.
    assert assignment.estimated_effort_minutes == 90

    # Confirm the application remembers that AI created this estimate.
    assert assignment.effort_estimate_source == "automatic"


@pytest.mark.django_db
def test_student_can_manually_override_effort_estimate():
    """A student override should replace the automatic effort estimate."""

    # Create the student who owns the assignment.
    user = get_user_model().objects.create_user(
        username="manual-effort-student",
        password="test-password-123",
    )

    # Start with an assignment that already has an automatic estimate.
    assignment = Assignment.objects.create(
        user=user,
        canvas_course_id=1002,
        canvas_assignment_id=2002,
        title="Programming Project",
        course="CS4300",
        due_date=timezone.now(),
        estimated_effort_minutes=90,
        effort_estimate_source="automatic",
    )

    # Simulate the student deciding that the assignment will actually require two hours.
    save_manual_effort_estimate(
        assignment=assignment,
        estimated_minutes=120,
    )

    # Reload the record to prove the new value was saved.
    assignment.refresh_from_db()

    # The student's estimate should replace the AI estimate.
    assert assignment.estimated_effort_minutes == 120

    # The source should now identify the estimate as manual.
    assert assignment.effort_estimate_source == "manual"


@pytest.mark.django_db
def test_manual_override_is_used_for_available_time_comparison():
    """Scheduling logic should use the student's updated estimate."""

    # Create the assignment owner.
    user = get_user_model().objects.create_user(
        username="schedule-effort-student",
        password="test-password-123",
    )

    # Create an assignment with an initial AI estimate.
    assignment = Assignment.objects.create(
        user=user,
        canvas_course_id=1003,
        canvas_assignment_id=2003,
        title="Final Project",
        course="CS4300",
        due_date=timezone.now(),
        estimated_effort_minutes=90,
        effort_estimate_source="automatic",
    )

    # The student overrides the estimate to three hours.
    save_manual_effort_estimate(
        assignment=assignment,
        estimated_minutes=180,
    )

    # Reload the persisted value before future scheduling uses it.
    assignment.refresh_from_db()

    # The student only has two hours available.
    enough_time = has_enough_available_time(
        estimated_minutes=assignment.estimated_effort_minutes,
        available_minutes=120,
    )

    # Scheduling should use the new 180-minute value,
    # correctly detecting that two hours is insufficient.
    assert enough_time is False


@pytest.mark.django_db
@pytest.mark.parametrize(
    "invalid_estimate",
    [
        0,
        -30,
        1.5,
        "90",
        None,
    ],
)
def test_invalid_manual_effort_estimate_is_rejected(invalid_estimate):
    """Manual effort estimates must be positive whole minutes."""

    # Create the assignment owner.
    user = get_user_model().objects.create_user(
        username=f"invalid-effort-{str(invalid_estimate)}",
    )

    # Create an assignment with no estimate yet.
    assignment = Assignment.objects.create(
        user=user,
        canvas_course_id=1004,
        canvas_assignment_id=3000 + user.id,
        title="Test Assignment",
        course="CS4300",
        due_date=timezone.now(),
    )

    # Invalid values should never reach the database.
    with pytest.raises(ValueError):
        save_manual_effort_estimate(
            assignment=assignment,
            estimated_minutes=invalid_estimate,
        )

    # Reload the record and confirm no invalid estimate was saved.
    assignment.refresh_from_db()

    assert assignment.estimated_effort_minutes is None
    assert assignment.effort_estimate_source is None
    