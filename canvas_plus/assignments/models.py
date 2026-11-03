"""DB models for assignment app"""

import uuid
from pathlib import Path

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models


class Assignment(models.Model):
    """User-owned Canvas assignment with local title, course, and due-date snapshots."""

    title = models.CharField(max_length=200)
    course = models.CharField(max_length=100)
    due_date = models.DateTimeField(null=True, blank=True)

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="assignments",
    )
    canvas_course_id = models.PositiveBigIntegerField()
    canvas_assignment_id = models.PositiveBigIntegerField()

    # Store the estimated amount of work required for the assignment.
    # The value is stored in minutes so scheduling logic has a consistent unit to work with.
    estimated_effort_minutes = models.PositiveIntegerField(
        null=True,
        blank=True,
    )

    # Track whether the current estimate came from the AI or was manually entered/overridden by the student.
    effort_estimate_source = models.CharField(
        max_length=20,
        choices=[
            ("automatic", "Automatic"),
            ("manual", "Manual"),
        ],
        null=True,
        blank=True,
    )

    class Meta:  # pylint: disable=too-few-public-methods
        """One student mirrors one Canvas assignment at most."""

        constraints = [
            models.UniqueConstraint(
                fields=["user", "canvas_assignment_id"],
                name="unique_user_canvas_assignment",
            ),
        ]

    def __str__(self):
        """returns title as string"""
        return str(self.title)


def study_file_upload_to(instance, filename):
    """Build a user-scoped path whose uuid name avoids collisions."""
    return f"study_files/{instance.user_id}/{uuid.uuid4()}{Path(filename).suffix}"


class StudyFile(models.Model):
    """A reusable file a student uploaded and can attach to assignments."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="study_files",
    )
    file = models.FileField(upload_to=study_file_upload_to)
    original_name = models.CharField(max_length=255)
    size = models.PositiveBigIntegerField()
    uploaded_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        """returns the uploaded file's original name"""
        return str(self.original_name)


class Attachment(models.Model):
    """A link between one student's assignment and one of their study files."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="attachments",
    )
    assignment = models.ForeignKey(
        Assignment,
        on_delete=models.CASCADE,
        related_name="attachments",
    )
    study_file = models.ForeignKey(
        StudyFile,
        on_delete=models.CASCADE,
        related_name="attachments",
    )
    category = models.CharField(max_length=50, blank=True, default="")

    class Meta:  # pylint: disable=too-few-public-methods
        """A file links to an assignment at most once."""

        constraints = [
            models.UniqueConstraint(
                fields=["assignment", "study_file"],
                name="unique_assignment_study_file",
            ),
        ]

    def clean(self):
        """Require the link, its assignment, and its file to share one owner."""
        super().clean()
        owners = {
            owner_id
            for owner_id in self._linked_owner_ids().values()
            if owner_id is not None
        }
        if len(owners) > 1:
            raise ValidationError(
                "Attachment user must match the assignment owner and the study file owner."
            )

    def _linked_owner_ids(self):
        """Collect the owner of this link and of the records it links."""
        # Foreign key attributes resolve to related instances only at runtime.
        # pylint: disable=no-member
        return {
            "user": self.user_id,
            "assignment": self.assignment.user_id if self.assignment_id else None,
            "study_file": self.study_file.user_id if self.study_file_id else None,
        }

    def save(self, *args, **kwargs):
        """Run ownership validation so ordinary saves cannot bypass it.

        Bulk operations (bulk_create, queryset update) skip this method; the
        write endpoints planned for #42 must scope and validate those instead.
        """
        self.clean()
        super().save(*args, **kwargs)

    def __str__(self):
        """returns the linked file and assignment"""
        return f"{self.study_file} on {self.assignment}"
