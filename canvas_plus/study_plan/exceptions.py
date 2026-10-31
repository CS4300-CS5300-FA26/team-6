"""Documented failures raised while generating study plans."""


class StudyPlanError(Exception):
    """Base class for study-plan generation failures."""


class EmptyAssignmentSelectionError(StudyPlanError):
    """No assignment IDs were selected for planning."""


class NoEligibleAssignmentsError(StudyPlanError):
    """None of the selected assignments can be scheduled."""


class InaccessibleAssignmentError(StudyPlanError):
    """A selected assignment does not belong to the requesting user."""


class NoUsableAvailabilityError(StudyPlanError):
    """No future, unoccupied availability is available for planning."""


class StudyPlanRetriesExhaustedError(StudyPlanError):
    """The planner could not obtain a valid plan after retrying inference."""