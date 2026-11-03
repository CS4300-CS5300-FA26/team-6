"""Read-only queries for displaying a student's study plan."""


def latest_plan_sessions(user, day=None):
    """Sessions of the user's most recent plan in start order, or None if they have no plan."""
    raise NotImplementedError
