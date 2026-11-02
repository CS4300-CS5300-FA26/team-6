"""Validating a batch of student files before any of it is saved."""
import logging

from django.db import transaction
from django.core.exceptions import ValidationError

from .models import Assignment, Attachment, StudyFile

logger = logging.getLogger(__name__)

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


def save_attachments(user, canvas_assignment, files):
    """Save a batch atomically, removing its stored bytes if any write fails."""
    # Django supplies model managers and bound file methods dynamically.
    # pylint: disable=no-member
    stored_files = []
    try:
        with transaction.atomic():
            assignment, _ = Assignment.objects.get_or_create(
                user=user,
                canvas_assignment_id=canvas_assignment["canvas_assignment_id"],
                defaults={
                    "canvas_course_id": canvas_assignment["canvas_course_id"],
                    "title": canvas_assignment["title"][:200],
                    "course": canvas_assignment["course_name"][:100],
                    "due_date": canvas_assignment["due_date"],
                },
            )
            for content in files:
                study_file = StudyFile(
                    user=user, original_name=content.name[:255], size=content.size,
                )
                study_file.file.save(content.name, content, save=False)
                stored_files.append((study_file.file.storage, study_file.file.name))
                study_file.save()
                Attachment.objects.create(
                    user=user, assignment=assignment, study_file=study_file, category="",
                )
    # Production S3 storage raises botocore errors beyond OSError.
    except Exception:  # pylint: disable=broad-exception-caught
        logger.exception("Unable to save attachment batch")
        for storage, name in stored_files:
            try:
                storage.delete(name)
            # Cleanup must preserve the original failure and try every stored file.
            except Exception:  # pylint: disable=broad-exception-caught
                logger.exception("Unable to remove stored file from failed attachment batch")
        raise
