"""Application configuration for the study plan app."""
from django.apps import AppConfig


class StudyPlanConfig(AppConfig):
    """Configure the study plan Django application."""
    default_auto_field = "django.db.models.BigAutoField"
    name = "study_plan"