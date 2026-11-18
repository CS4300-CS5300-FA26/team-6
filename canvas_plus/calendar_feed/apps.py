"""Application configuration for calendar feeds."""

from django.apps import AppConfig


class CalendarFeedConfig(AppConfig):
    """Configure the calendar-feed Django application."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "calendar_feed"