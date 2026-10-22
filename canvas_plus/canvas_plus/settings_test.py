"""Django Settings Used specifically for testing."""

# import normal Django settings
from .settings import * #pylint: disable=wildcard-import,unused-wildcard-import
from . import settings as base_settings

#Copy normal installed apps and add behave-django.
INSTALLED_APPS = [
    *base_settings.INSTALLED_APPS,
    "behave_django",
]
