"""Django Settings Used specifically for testing."""

# import normal Django settings
from .settings import * #pylint: disable=wildcard-import,unused-wildcard-import
from . import settings as base_settings

#Copy normal installed apps and add behave-django.
INSTALLED_APPS = [
    *base_settings.INSTALLED_APPS,
    "behave_django",
]

# Tests render templates without running collectstatic, so they must not depend
# on WhiteNoise's generated staticfiles manifest.
STORAGES = {
    **base_settings.STORAGES,
    "staticfiles": {
        "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
    },
}

# Cached Canvas data must not leak between tests; caching tests opt in to LOCMEM_CACHE.
CACHES = {"default": {"BACKEND": "django.core.cache.backends.dummy.DummyCache"}}
LOCMEM_CACHE = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
