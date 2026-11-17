"""Subscription and calendar-feed service entry points."""

import hashlib
import secrets

from .models import CalendarSubscription


def issue_subscription(user):
    """Issue or rotate a user's calendar subscription credential."""
    token = secrets.token_urlsafe(32)
    token_digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
    CalendarSubscription.objects.update_or_create(
        user=user,
        defaults={"token_digest": token_digest},
    )
    return token


def get_subscription_by_token(token):
    """Resolve a bearer token without persisting or returning its plaintext."""
    token_digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
    return CalendarSubscription.objects.select_related("user").filter(
        token_digest=token_digest
    ).first()


def generate_feed(user):
    """Build the user's current calendar feed from local records."""
    raise NotImplementedError
