"""Application configuration for the availability app."""
from django.apps import AppConfig


class AvailabilityConfig(AppConfig):
    """Configure the availability Django application."""
    default_auto_field = "django.db.models.BigAutoField"
    name = 'availability'
