"""Bound calendar-feed acceptance steps for the implementation scaffold."""

# Behave decorators are callable; pylint cannot infer their dynamic registration.
# pylint: disable=not-callable

from behave import when


@when("I issue, copy, and rotate a personal subscription URL")
def step_issue_rotate_calendar_url(context):
    """Stop at the deliberate subscription journey boundary."""
    del context
    raise NotImplementedError


@when("I fetch assignment and study-session events from local records")
def step_fetch_assignment_and_session_events(context):
    """Stop at the deliberate local event-fetch journey boundary."""
    del context
    raise NotImplementedError


@when("I subscribe to a valid empty calendar feed using local records")
def step_subscribe_to_empty_calendar(context):
    """Stop at the deliberate empty-feed journey boundary."""
    del context
    raise NotImplementedError
