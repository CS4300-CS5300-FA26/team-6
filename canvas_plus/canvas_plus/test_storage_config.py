"""Storage selection keeps uploads local or private according to configuration."""

import pytest
from django.core.exceptions import ImproperlyConfigured

from .storage_config import storages_from_env


@pytest.mark.unit
def test_no_bucketeer_configuration_in_debug_uses_filesystem():
    """Given no bucket settings in development, uploads stay on disk."""
    assert storages_from_env({}, debug=True) == {
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {
            "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
        },
    }


@pytest.mark.unit
def test_no_bucketeer_configuration_in_production_fails_at_startup():
    """Given no bucket settings in production, refuse to start on ephemeral storage."""
    with pytest.raises(ImproperlyConfigured) as error:
        storages_from_env({}, debug=False)

    assert str(error.value) == (
        "Missing Bucketeer configuration: BUCKETEER_AWS_ACCESS_KEY_ID, "
        "BUCKETEER_AWS_SECRET_ACCESS_KEY, BUCKETEER_AWS_REGION, BUCKETEER_BUCKET_NAME"
    )


@pytest.mark.unit
def test_complete_bucketeer_configuration_uses_private_s3():
    """Given all four bucket settings, uploads use exactly the private S3 options."""
    assert storages_from_env({
        "BUCKETEER_AWS_ACCESS_KEY_ID": "fake-access",
        "BUCKETEER_AWS_SECRET_ACCESS_KEY": "fake-secret",
        "BUCKETEER_AWS_REGION": "fake-region",
        "BUCKETEER_BUCKET_NAME": "fake-bucket",
    }, debug=False) == {
        "default": {
            "BACKEND": "storages.backends.s3.S3Storage",
            "OPTIONS": {
                "access_key": "fake-access",
                "secret_key": "fake-secret",
                "region_name": "fake-region",
                "bucket_name": "fake-bucket",
                "default_acl": None,
                "querystring_auth": True,
                "file_overwrite": False,
            },
        },
        "staticfiles": {
            "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
        },
    }


@pytest.mark.unit
@pytest.mark.parametrize("debug", [True, False])
def test_partial_bucketeer_configuration_names_missing_keys_without_values(debug):
    """Given incomplete bucket settings, fail closed without exposing credentials."""
    with pytest.raises(ImproperlyConfigured) as error:
        storages_from_env({"BUCKETEER_AWS_ACCESS_KEY_ID": "do-not-leak-this-value"}, debug=debug)

    assert str(error.value) == (
        "Missing Bucketeer configuration: BUCKETEER_AWS_SECRET_ACCESS_KEY, "
        "BUCKETEER_AWS_REGION, BUCKETEER_BUCKET_NAME"
    )
    assert "do-not-leak-this-value" not in str(error.value)
