"""Subscription and calendar-feed service entry points."""


def issue_subscription(user):
    """Issue or rotate a user's calendar subscription credential."""
    raise NotImplementedError


def generate_feed(user):
    """Build the user's current calendar feed from local records."""
    raise NotImplementedError