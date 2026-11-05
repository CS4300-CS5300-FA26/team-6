"""Generate and persist study plans."""

from dataclasses import dataclass

from django.db import transaction

from ai_inference import infer
from ai_inference.exceptions import AIInferenceError
from assignments.models import Assignment
from assignments.canvas_sync import refresh_selected_assignment_snapshots
from study_plan.availability_windows import prepare_availability_windows
from study_plan.exceptions import (
    EmptyAssignmentSelectionError,
    InaccessibleAssignmentError,
    NoEligibleAssignmentsError,
    NoUsableAvailabilityError,
    StudyPlanRetriesExhaustedError,
)
from study_plan.effort_estimation import estimate_and_save_assignment_effort
from study_plan.models import StudyPlan as PersistedStudyPlan
from study_plan.models import StudySession
from study_plan.prompt import build_plan_inference_input
from study_plan.schema import StudyPlan as StudyPlanResponse
from study_plan.validation import (
    PlanValidationError,
    validate_estimated_effort,
    validate_plan,
)

GENERATE_ATTEMPTS = 2


@dataclass(frozen=True)
class ProposalValidationContext:
    """Inputs needed to validate a generated proposal."""

    assignment_deadlines: dict
    free_windows: list
    occupied_sessions: object
    assignments: list
    allow_late: bool


def generate_plan(user, assignment_ids, allow_late=False):
    """Generate, validate, and persist a plan for the user's assignments.

    Assignments and availability are scoped to the requesting user. Inference and
    validation complete before a persisted plan is created.
    """
    selected_ids = list(dict.fromkeys(assignment_ids))
    if not selected_ids:
        raise EmptyAssignmentSelectionError("Select at least one assignment.")

    assignments = list(
        Assignment.objects.filter(user=user, pk__in=selected_ids)
    )
    if len(assignments) != len(selected_ids):
        raise InaccessibleAssignmentError(
            "One or more selected assignments are inaccessible."
        )

    notices = refresh_selected_assignment_snapshots(user, assignments)
    assignments = list(
        Assignment.objects.filter(user=user, pk__in=selected_ids)
    )
    eligible_assignments, eligibility_notices = _filter_eligible_assignments(assignments)
    notices.extend(eligibility_notices)

    if not eligible_assignments:
        raise NoEligibleAssignmentsError(
            "; ".join(notices) or "No selected assignments are eligible to plan."
        )

    occupied_sessions = StudySession.objects.filter(plan__user=user).select_related("plan")
    free_windows = prepare_availability_windows(
        user,
        occupied_sessions=occupied_sessions,
    )
    if not free_windows:
        raise NoUsableAvailabilityError("No future unoccupied availability is available.")

    system_prompt, content = build_plan_inference_input(
        eligible_assignments,
        free_windows,
        allow_late=allow_late,
    )
    assignment_deadlines = {
        assignment.id: assignment.due_date
        for assignment in eligible_assignments
    }

    validation_context = ProposalValidationContext(
        assignment_deadlines=assignment_deadlines,
        free_windows=free_windows,
        occupied_sessions=occupied_sessions,
        assignments=eligible_assignments,
        allow_late=allow_late,
    )
    proposal = _request_valid_proposal(system_prompt, content, validation_context)
    notices.extend(proposal.notices)
    notices.extend(_remaining_effort_notices(proposal, eligible_assignments))
    with transaction.atomic():
        persisted_plan = PersistedStudyPlan.objects.create(user=user, notices=notices)
        StudySession.objects.bulk_create(
            [
                StudySession(
                    plan=persisted_plan,
                    assignment_id=session.assignment_id,
                    start=session.start,
                    end=session.end,
                    late=session.late,
                )
                for session in proposal.sessions
            ]
        )
    return persisted_plan


def _filter_eligible_assignments(assignments):
    """Return schedulable assignments and notices for skipped ones."""
    eligible_assignments = []
    notices = []
    for assignment in assignments:
        estimate = getattr(assignment, "estimated_effort_minutes", None)
        if assignment.due_date is None:
            notices.append(f"{assignment.title} was skipped because it has no due date.")
        else:
            if not isinstance(estimate, int) or isinstance(estimate, bool) or estimate <= 0:
                try:
                    estimate_and_save_assignment_effort(
                        assignment,
                        assignment.description,
                    )
                except AIInferenceError:
                    notices.append(
                        f"{assignment.title} was skipped because its effort estimate "
                        "could not be generated."
                    )
                    continue
                estimate = assignment.estimated_effort_minutes

            if not isinstance(estimate, int) or isinstance(estimate, bool) or estimate <= 0:
                notices.append(
                    f"{assignment.title} was skipped because it has no positive effort estimate."
                )
            else:
                eligible_assignments.append(assignment)
    return eligible_assignments, notices


def _request_valid_proposal(system_prompt, content, validation_context):
    """Retry inference once when it fails or returns an invalid proposal."""
    for attempt in range(GENERATE_ATTEMPTS):
        try:
            proposal = infer(system_prompt, content, StudyPlanResponse)
            _validate_proposal(proposal, validation_context)
        except (AIInferenceError, PlanValidationError) as error:
            if attempt == GENERATE_ATTEMPTS - 1:
                raise StudyPlanRetriesExhaustedError(
                    f"Could not generate a valid study plan after {GENERATE_ATTEMPTS} attempts."
                ) from error
        else:
            return proposal
    raise AssertionError("Inference retry loop ended unexpectedly.")


def _validate_proposal(proposal, context):
    """Validate scheduling constraints and estimated effort."""
    validate_plan(
        proposal,
        context.assignment_deadlines,
        context.free_windows,
        occupied_sessions=context.occupied_sessions,
        allow_late=context.allow_late,
    )
    validate_estimated_effort(proposal, context.assignments)


def _remaining_effort_notices(proposal, assignments):
    """Report estimated effort that was not represented by proposed sessions."""
    scheduled_minutes = {}
    for session in proposal.sessions:
        duration = session.end - session.start
        scheduled_minutes[session.assignment_id] = (
            scheduled_minutes.get(session.assignment_id, 0)
            + int(duration.total_seconds() // 60)
        )

    notices = []
    for assignment in assignments:
        remaining_minutes = max(
            0,
            assignment.estimated_effort_minutes - scheduled_minutes.get(assignment.id, 0),
        )
        if remaining_minutes:
            notices.append(
                f"{assignment.title} has {remaining_minutes} minutes of effort unscheduled."
            )
    return notices
