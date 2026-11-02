"""Tests for AI-assisted assignment effort estimation."""

from datetime import datetime
from unittest.mock import patch

import pytest

from study_plan.effort_estimation import (
    estimate_assignment_effort,
    has_enough_available_time,
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