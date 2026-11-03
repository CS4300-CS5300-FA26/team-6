"""Migration tests for the user-owned assignment schema change (#42)."""

# Django wires managers (objects) at runtime; this project lints without
# pylint-django, so pylint cannot infer those members.
# pylint: disable=no-member

import pytest
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase
from django.utils import timezone

from assignments.models import Assignment, Attachment, StudyFile  # pylint: disable=import-error
from assignments.test_models import use_temp_media_root  # pylint: disable=import-error

PRIOR_MIGRATION = ("assignments", "0002_alter_assignment_id")
OWNERSHIP_MIGRATION = ("assignments", "0003_assignment_user_studyfile_attachment")


@pytest.mark.integration
class AssignmentOwnershipMigrationTests(TransactionTestCase):
    """The ownership migration applies to an empty schema and refuses legacy rows."""

    def setUp(self):
        """Store uploads in a throwaway MEDIA_ROOT and roll the schema back to 0002."""
        use_temp_media_root(self)
        self.prior_apps = self._migrate_to(PRIOR_MIGRATION)
        super().setUp()

    def tearDown(self):
        """Whatever a test did to the schema, the suite must find every app migrated."""
        self._restore_schema()
        super().tearDown()

    def _executor(self):
        """A fresh executor whose loader reflects the database's applied state."""
        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        return executor

    def _migrate_to(self, target):
        """Migrate the assignments app to target and return that state's apps."""
        executor = self._executor()
        executor.migrate([target])
        return executor.loader.project_state([target]).apps

    def _restore_schema(self):
        """Bring every app back to its latest migration, clearing only test rows."""
        executor = self._executor()
        if OWNERSHIP_MIGRATION not in executor.recorder.applied_migrations():
            # A refused migration leaves test-created legacy rows behind; they are
            # test data, so clear the way and bring the schema back to latest.
            with connection.cursor() as cursor:
                cursor.execute("DELETE FROM assignments_assignment")
        executor.migrate(executor.loader.graph.leaf_nodes())

    def test_applies_on_empty_prior_schema(self):
        """Given an empty 0002 schema, the ownership migration applies cleanly."""

        # Migrate to the ownership schema and capture the historical app registry.
        ownership_apps = self._migrate_to(OWNERSHIP_MIGRATION)

        # Use models exactly as they existed at migration 0003.
        HistoricalAssignment = ownership_apps.get_model(
            "assignments",
            "Assignment",
        )
        HistoricalStudyFile = ownership_apps.get_model(
            "assignments",
            "StudyFile",
        )
        HistoricalAttachment = ownership_apps.get_model(
            "assignments",
            "Attachment",
        )

        # Create the user using the current auth model.
        user = get_user_model().objects.create_user(
            username="migration-owner",
        )

        # Create an assignment using the historical 0003 schema.
        assignment = HistoricalAssignment.objects.create(
            user_id=user.id,
            title="Owned project",
            course="CS 4300",
            canvas_course_id=42,
            canvas_assignment_id=101,
        )

        # Confirm the nullable due_date field behaves as expected.
        self.assertIsNone(
            HistoricalAssignment.objects.get(
                pk=assignment.pk
            ).due_date
        )

        # Confirm the uniqueness constraint added by the migration works.
        with transaction.atomic():
            with self.assertRaises(IntegrityError):
                HistoricalAssignment.objects.create(
                    user_id=user.id,
                    canvas_course_id=42,
                    title="Duplicate mirror",
                    course="CS 4300",
                    canvas_assignment_id=101,
                )

        # Create a historical StudyFile using the 0003 schema.
        study_file = HistoricalStudyFile.objects.create(
            user_id=user.id,
            file=SimpleUploadedFile(
                "notes.pdf",
                b"tiny",
            ),
            original_name="notes.pdf",
            size=4,
        )

        # Create a historical attachment using foreign-key IDs.
        HistoricalAttachment.objects.create(
            user_id=user.id,
            assignment_id=assignment.id,
            study_file_id=study_file.id,
        )

        # Confirm the attachment row was created.
        self.assertEqual(
            HistoricalAttachment.objects.filter(
                assignment_id=assignment.id
            ).count(),
            1,
         )

    def test_refuses_legacy_rows_and_preserves_them(self):
        """Given historical unowned rows, the migration refuses and changes nothing."""
        legacy_assignment = self.prior_apps.get_model("assignments", "Assignment")
        legacy_assignment.objects.create(
            title="Legacy Homework", course="CS 4300", due_date=timezone.now()
        )

        with self.assertRaises(RuntimeError) as raised:
            self._migrate_to(OWNERSHIP_MIGRATION)

        message = str(raised.exception).lower()
        self.assertIn("1 historical assignment row", message)
        self.assertIn("export", message)
        self.assertIn("reconcile", message)

        # The refusal changed neither the data nor the schema.
        self.assertEqual(legacy_assignment.objects.count(), 1)
        kept = legacy_assignment.objects.get()
        self.assertEqual(kept.title, "Legacy Homework")
        self.assertEqual(kept.course, "CS 4300")
        legacy_assignment.objects.create(
            title="Second legacy", course="CS 5000", due_date=timezone.now()
        )
        self.assertEqual(legacy_assignment.objects.count(), 2)
        self.assertNotIn(
            OWNERSHIP_MIGRATION, self._executor().recorder.applied_migrations()
        )
