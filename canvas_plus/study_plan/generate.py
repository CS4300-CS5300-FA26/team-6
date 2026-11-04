"""Generate and persist a validated study plan with the configured AI service."""

import json

from django.db import transaction

from ai_inference import AIInferenceError, infer
from assignments.models import Assignment
from study_plan.availability_windows import prepare_availability_windows
from study_plan.exceptions import (
    EmptyAssignmentSelectionError,
    InaccessibleAssignmentError,
    NoEligibleAssignmentsError,
    NoUsableAvailabilityError,
    StudyPlanRetriesExhaustedError,
)
from study_plan.models import StudyPlan as PersistedStudyPlan
from study_plan.models import StudySession
from study_plan.schema import StudyPlan as ProposedStudyPlan
from study_plan.validation import PlanValidationError, validate_plan


MAX_ATTEMPTS = 2


def generate_plan(user, assignment_ids, allow_late=False):
    """Ask AI for sessions, validate them, then save a new plan for the user."""
    selected_ids = _normalize_assignment_ids(assignment_ids)
    if not selected_ids:
        raise EmptyAssignmentSelectionError("Select at least one assignment.")

    selected = list(
        Assignment.objects.filter(user=user, pk__in=selected_ids)
        .order_by("due_date", "pk")
    )
    if len(selected) != len(selected_ids):
        raise InaccessibleAssignmentError("A selected assignment is unavailable.")

    eligible = [assignment for assignment in selected if assignment.due_date]
    if not eligible:
        raise NoEligibleAssignmentsError("Selected assignments need a due date.")

    occupied_sessions = StudySession.objects.filter(plan__user=user)
    availability = prepare_availability_windows(
        user,
        occupied_sessions=occupied_sessions,
    )
    if not availability:
        raise NoUsableAvailabilityError("Add future availability before generating a plan.")

    assignment_deadlines = {
        assignment.pk: assignment.due_date
        for assignment in eligible
    }
    prompt_content = _build_prompt_content(eligible, availability, allow_late)
    proposal = None
    last_error = None
    for _ in range(MAX_ATTEMPTS):
        try:
            proposal = infer(
                "Create a practical study schedule using only the supplied assignments "
                "and availability. Schedule sessions in 15-minute increments, never "
                "overlap sessions, and respect each assignment deadline. Set late=true "
                "only for sessions ending after a deadline, and only when late scheduling "
                "is enabled. Return sessions only for the supplied assignment IDs.",
                prompt_content,
                ProposedStudyPlan,
            )
            validate_plan(
                proposal,
                assignment_deadlines,
                availability,
                occupied_sessions=occupied_sessions,
                allow_late=allow_late,
            )
            break
        except (AIInferenceError, PlanValidationError) as error:
            last_error = error
            proposal = None

    if proposal is None:
        raise StudyPlanRetriesExhaustedError(
            "AI could not create a valid study plan after retrying."
        ) from last_error

    with transaction.atomic():
        plan = PersistedStudyPlan.objects.create(
            user=user,
            notices=list(proposal.notices),
        )
        StudySession.objects.bulk_create([
            StudySession(
                plan=plan,
                assignment=next(
                    assignment
                    for assignment in eligible
                    if assignment.pk == session.assignment_id
                ),
                start=session.start,
                end=session.end,
                late=session.late,
            )
            for session in proposal.sessions
        ])
    return plan


def _normalize_assignment_ids(assignment_ids):
    """Parse submitted primary keys and discard duplicate values."""
    normalized = []
    for assignment_id in assignment_ids:
        try:
            parsed_id = int(assignment_id)
        except (TypeError, ValueError):
            raise InaccessibleAssignmentError(
                "A selected assignment is unavailable."
            ) from None
        if parsed_id not in normalized:
            normalized.append(parsed_id)
    return normalized


def _build_prompt_content(assignments, availability, allow_late):
    """Serialize only the selected assignment facts and available time windows."""
    request_data = {
        "assignments": [
            {
                "id": assignment.pk,
                "title": assignment.title,
                "course": assignment.course,
                "deadline": assignment.due_date.isoformat(),
            }
            for assignment in assignments
        ],
        "availability": [
            {"start": start.isoformat(), "end": end.isoformat()}
            for start, end in availability
        ],
        "allow_late": allow_late,
    }
    return json.dumps(request_data)