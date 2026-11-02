"""Upload storage configuration."""

from django.core.exceptions import ImproperlyConfigured


def storages_from_env(env):
    """Use private Bucketeer storage only when its configuration is complete."""
    keys = (
        "BUCKETEER_AWS_ACCESS_KEY_ID",
        "BUCKETEER_AWS_SECRET_ACCESS_KEY",
        "BUCKETEER_AWS_REGION",
        "BUCKETEER_BUCKET_NAME",
    )
    missing = [key for key in keys if not env.get(key)]
    default = {"BACKEND": "django.core.files.storage.FileSystemStorage"}
    if len(missing) != len(keys):
        if missing:
            raise ImproperlyConfigured(
                f"Missing Bucketeer configuration: {', '.join(missing)}"
            )
        default = {
            "BACKEND": "storages.backends.s3.S3Storage",
            "OPTIONS": {
                "access_key": env[keys[0]],
                "secret_key": env[keys[1]],
                "region_name": env[keys[2]],
                "bucket_name": env[keys[3]],
                "default_acl": None,
                "querystring_auth": True,
                "file_overwrite": False,
            },
        }
    return {
        "default": default,
        "staticfiles": {
            "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
        },
    }
