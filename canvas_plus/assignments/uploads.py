"""Validating a batch of student files before any of it is saved."""
from django.core.exceptions import ValidationError

# Binary 25 MiB (26,214,400 bytes), so no student is rejected for a batch their
# OS shows as 25 MB or less. macOS Finder uses decimal units and may therefore
# show an accepted file as up to 26.2 MB, which is accepted deliberately.
MAX_UPLOAD_BATCH_BYTES = 25 * 1024 * 1024


def validate_batch(files):
    """Reject an empty batch or one whose combined size exceeds the limit."""
    if not files:
        raise ValidationError("Choose at least one file to upload.")
    if sum(item.size for item in files) > MAX_UPLOAD_BATCH_BYTES:
        raise ValidationError("File batch exceeds 25 MB limit")
