"""Study-plan proposal validation API"""


class PlanValidationError(ValueError):
    """Raised when an AI-proposed plan violates scheduling constraints."""


def validate_plan(
    plan,
    assignment_deadlines,
    availability_windows,
    *,
    occupied_sessions=(),
    allow_late=False,
):
    """Validate a proposed plan against assignment and time-window constraints.

    Args:
        plan: Structured plan proposal to validate.
        assignment_deadlines: Mapping from selected assignment IDs to deadlines.
        availability_windows: Allowed aware start/end datetime pairs.
        occupied_sessions: Earlier sessions unavailable for new scheduling.
        allow_late: Whether sessions past an assignment deadline may be accepted.

    Raises:
        NotImplementedError: Until proposal validation is implemented in T013.
    """
    raise NotImplementedError("Study-plan validation is not implemented yet.")