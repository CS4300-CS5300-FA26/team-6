"""Tests for calendar subscription lifecycle and credential privacy."""

import hashlib
import re
from urllib.parse import urlsplit

import pytest
from django.urls import reverse

from .models import CalendarSubscription


pytestmark = pytest.mark.django_db
SETTINGS_URL = "/accounts/settings/"


def signed_in_student(client, django_user_model):
    """Return the test client authenticated as a newly created student."""
    user = django_user_model.objects.create_user(username="calendar-student")
    client.force_login(user)
    return user


def copyable_feed_url(response):
    """Extract the absolute subscription URL revealed by a settings action."""
    content = response.content.decode(response.charset)
    matches = set(
        re.findall(r"https?://[^\s\"'<>]+/calendar-feed/[^\s\"'<>]+\.ics", content)
    )
    assert len(matches) == 1, "Expected one copyable absolute calendar feed URL."
    return matches.pop()


def feed_token(feed_url):
    """Return the bearer secret embedded in an absolute feed URL."""
    return urlsplit(feed_url).path.rsplit("/", maxsplit=1)[-1].removesuffix(".ics")


def token_digest(token):
    """Return the persisted SHA-256 digest for a fixture bearer token."""
    return hashlib.sha256(token.encode()).hexdigest()


def test_student_creates_and_rotates_subscription_url(client, django_user_model):
    """Creating a feed URL is personal, and rotating it rejects the old URL."""
    signed_in_student(client, django_user_model)

    created = client.post(SETTINGS_URL, {"action": "calendar"})
    assert created.status_code == 200
    first_url = copyable_feed_url(created)

    rotated = client.post(SETTINGS_URL, {"action": "calendar"})
    assert rotated.status_code == 200
    second_url = copyable_feed_url(rotated)
    assert second_url != first_url

    old_feed = client.get(urlsplit(first_url).path)
    assert old_feed.status_code != 200


def test_subscription_secret_is_one_time_and_not_stored_in_plaintext(
    client, django_user_model
):
    """The bearer URL is revealed once and only its digest is persisted."""
    user = signed_in_student(client, django_user_model)

    created = client.post(SETTINGS_URL, {"action": "calendar"})
    assert created.status_code == 200
    feed_url = copyable_feed_url(created)
    secret = feed_token(feed_url)

    settings_page = client.get(SETTINGS_URL)
    assert settings_page.status_code == 200
    settings_content = settings_page.content.decode(settings_page.charset)
    assert feed_url not in settings_content
    assert secret not in settings_content

    subscription = CalendarSubscription.objects.get(user=user)
    stored_values = CalendarSubscription.objects.filter(pk=subscription.pk).values().first()
    assert secret not in repr(stored_values)


def test_feed_requires_active_valid_subscription(client, django_user_model):
    """Only the active bearer credential for an active account may fetch a feed."""
    user = django_user_model.objects.create_user(username="feed-owner")
    original_token = "original-calendar-secret"
    rotated_token = "rotated-calendar-secret"
    CalendarSubscription.objects.create(
        user=user,
        token_digest=token_digest(original_token),
    )

    def request_feed(token):
        return client.get(reverse("calendar_feed", args=[token]))

    assert request_feed(original_token).status_code == 200
    assert request_feed("invalid-calendar-secret").status_code != 200

    subscription = CalendarSubscription.objects.get(user=user)
    subscription.token_digest = token_digest(rotated_token)
    subscription.save(update_fields=["token_digest"])
    assert request_feed(original_token).status_code != 200
    assert request_feed(rotated_token).status_code == 200

    user.is_active = False
    user.save(update_fields=["is_active"])
    assert request_feed(rotated_token).status_code != 200

    user.delete()
    assert request_feed(rotated_token).status_code != 200
