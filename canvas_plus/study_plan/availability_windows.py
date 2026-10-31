"""Availability preparation API; scheduling behavior is implemented in T011."""


def prepare_availability_windows(user, now=None, occupied_sessions=()):
    """Return the user's usable aware time intervals.

    Args:
        user: Owner whose availability should be prepared.
        now: Optional aware reference datetime used to discard past time.
        occupied_sessions: Earlier sessions to subtract from availability.

    Raises:
        NotImplementedError: Until the availability-window implementation lands.
    """
    raise NotImplementedError("Availability window preparation is not implemented yet.")