"""Ownership migration for #42: user-owned assignments, study files, attachments.

Hand-written so the required user key is added with NO default (the preflight
verifies the table is empty first); no artificial user or Canvas ids are ever
written. Reversing never rewrites assignment data.
"""

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models

from assignments.models import study_file_upload_to


def require_empty_assignments_table(apps, schema_editor):  # pylint: disable=unused-argument
    """Refuse to migrate historical Assignment rows instead of guessing owners."""
    assignment = apps.get_model("assignments", "Assignment")
    legacy_count = assignment.objects.using(schema_editor.connection.alias).count()
    if legacy_count:
        raise RuntimeError(
            f"Cannot apply this migration: {legacy_count} historical Assignment "
            "row(s) exist without a user. Export those rows manually (title, "
            "course, due_date), reconcile or remove them so the table is empty, "
            "then run this migration again. No rows were changed or deleted."
        )


def noop_reverse(apps, schema_editor):  # pylint: disable=unused-argument
    """Reversing this migration must not rewrite assignment data."""


class Migration(migrations.Migration):
    """User-owned assignments, study files, and attachments for issue #42."""

    dependencies = [
        ("assignments", "0002_alter_assignment_id"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.RunPython(require_empty_assignments_table, noop_reverse),
        migrations.AlterField(
            model_name="assignment",
            name="due_date",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="assignment",
            name="user",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="assignments",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name="assignment",
            name="canvas_course_id",
            field=models.PositiveBigIntegerField(),
        ),
        migrations.AddField(
            model_name="assignment",
            name="canvas_assignment_id",
            field=models.PositiveBigIntegerField(),
        ),
        migrations.CreateModel(
            name="StudyFile",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("file", models.FileField(upload_to=study_file_upload_to)),
                ("original_name", models.CharField(max_length=255)),
                ("size", models.PositiveBigIntegerField()),
                ("uploaded_at", models.DateTimeField(auto_now_add=True)),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="study_files",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
        ),
        migrations.CreateModel(
            name="Attachment",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("category", models.CharField(blank=True, default="", max_length=50)),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="attachments",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "assignment",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="attachments",
                        to="assignments.assignment",
                    ),
                ),
                (
                    "study_file",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="attachments",
                        to="assignments.studyfile",
                    ),
                ),
            ],
        ),
        migrations.AddConstraint(
            model_name="assignment",
            constraint=models.UniqueConstraint(
                fields=("user", "canvas_assignment_id"),
                name="unique_user_canvas_assignment",
            ),
        ),
        migrations.AddConstraint(
            model_name="attachment",
            constraint=models.UniqueConstraint(
                fields=("assignment", "study_file"),
                name="unique_assignment_study_file",
            ),
        ),
    ]
