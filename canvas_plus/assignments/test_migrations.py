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
        self._migrate_to(OWNERSHIP_MIGRATION)

        user = get_user_model().objects.create_user(username="migration-owner")
        assignment = Assignment.objects.create(
            user=user, title="Owned project", course="CS 4300",
            canvas_course_id=42, canvas_assignment_id=101,
        )
        self.assertIsNone(Assignment.objects.get(pk=assignment.pk).due_date)

        with transaction.atomic():
            with self.assertRaises(IntegrityError):
                Assignment.objects.create(
                    canvas_course_id=42,
                    user=user, title="Duplicate mirror", course="CS 4300",
                    canvas_assignment_id=101,
                )

        study_file = StudyFile.objects.create(
            user=user,
            file=SimpleUploadedFile("notes.pdf", b"tiny"),
            original_name="notes.pdf",
            size=4,
        )
        Attachment.objects.create(
            user=user, assignment=assignment, study_file=study_file
        )
        self.assertEqual(assignment.attachments.count(), 1)

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
