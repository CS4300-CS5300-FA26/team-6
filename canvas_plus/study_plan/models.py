"""Persisted study plans and their scheduled assignment sessions."""

from django.conf import settings
from django.db import models

from assignments.models import Assignment


class StudyPlan(models.Model):
    """A generated study plan belonging to one user."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="study_plans",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    notices = models.JSONField(default=list)


class StudySession(models.Model):
    """A scheduled block of study time for one assignment."""

    plan = models.ForeignKey(
        StudyPlan,
        on_delete=models.CASCADE,
        related_name="sessions",
    )
    assignment = models.ForeignKey(
        Assignment,
        on_delete=models.CASCADE,
        related_name="study_sessions",
    )
    start = models.DateTimeField()
    end = models.DateTimeField()
    late = models.BooleanField(default=False)