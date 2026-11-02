"""Unit tests for the user-owned assignment, study file, and attachment models (#42)."""

# Django wires managers (objects) and related-field attributes at runtime; this
# project lints without pylint-django, so pylint cannot infer those members.
# pylint: disable=no-member

import shutil
import tempfile
from pathlib import Path

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings

from assignments.models import Assignment, Attachment, StudyFile  # pylint: disable=import-error

PASSWORD = "Correct-Pass-123"
FILE_CONTENT = b"tiny study file"


def make_user(username):
    """One student account, the owner of all their records."""
    return get_user_model().objects.create_user(username=username, password=PASSWORD)


def upload(user, name="notes.pdf"):
    """A tiny stored StudyFile with its original name and size recorded."""
    return StudyFile.objects.create(
        user=user,
        file=SimpleUploadedFile(name, FILE_CONTENT),
        original_name=name,
        size=len(FILE_CONTENT),
    )


def use_temp_media_root(test):
    """Point file storage at a temp directory that is removed afterwards."""
    media_root = tempfile.mkdtemp(prefix="canvas_plus_media_")
    test.addCleanup(shutil.rmtree, media_root, ignore_errors=True)
    media_override = override_settings(MEDIA_ROOT=media_root)
    media_override.enable()
    test.addCleanup(media_override.disable)
    return media_root


class MediaRootTestCase(TestCase):
    """A test case whose uploads land in a throwaway MEDIA_ROOT."""

    def setUp(self):
        """Isolate uploads in a throwaway directory."""
        super().setUp()
        self.media_root = use_temp_media_root(self)


@pytest.mark.unit
class AssignmentModelTests(TestCase):
    """Assignments are owned by one student and uniquely mirror one Canvas item."""

    def setUp(self):
        """Every assignment in these tests belongs to one student."""
        self.user = make_user("assignment-owner")

    def test_str_returns_title(self):
        """The string form is the assignment title."""
        assignment = Assignment.objects.create(
            canvas_course_id=42, canvas_assignment_id=101,
            user=self.user, title="Essay 2", course="CS 4300"
        )

        self.assertEqual(str(assignment), "Essay 2")

    def test_assignment_without_due_date_or_attachments_persists(self):
        """An undated Canvas assignment saves with a blank due date and no links."""
        assignment = Assignment.objects.create(
            canvas_course_id=42, canvas_assignment_id=101,
            user=self.user, title="Undated Quiz", course="CS 4300"
        )

        assignment.refresh_from_db()
        self.assertIsNone(assignment.due_date)
        self.assertEqual(assignment.attachments.count(), 0)

    def test_same_canvas_assignment_id_is_allowed_for_different_users(self):
        """Two students can each mirror the same Canvas assignment."""
        other = make_user("other-student")
        Assignment.objects.create(
            user=self.user, title="Project", course="CS 4300",
            canvas_course_id=42, canvas_assignment_id=101,
        )
        Assignment.objects.create(
            user=other, title="Project", course="CS 4300",
            canvas_course_id=42, canvas_assignment_id=101,
        )

        self.assertEqual(Assignment.objects.filter(canvas_assignment_id=101).count(), 2)
        self.assertEqual(Assignment.objects.filter(user=self.user).count(), 1)
        self.assertEqual(Assignment.objects.filter(user=other).count(), 1)

    def test_duplicate_canvas_assignment_id_per_user_is_rejected(self):
        """A student cannot mirror the same Canvas assignment twice."""
        Assignment.objects.create(
            canvas_course_id=42,
            user=self.user, title="Project", course="CS 4300", canvas_assignment_id=101
        )

        with transaction.atomic():
            with self.assertRaises(IntegrityError):
                Assignment.objects.create(
                    canvas_course_id=42,
                    user=self.user, title="Project again", course="CS 4300",
                    canvas_assignment_id=101,
                )

        self.assertEqual(Assignment.objects.filter(user=self.user).count(), 1)

    def test_canvas_identity_is_required(self):
        """A local record must identify both its Canvas assignment and course."""
        for missing in ("canvas_course_id", "canvas_assignment_id"):
            with self.subTest(missing=missing):
                fields = {"canvas_course_id": 42, "canvas_assignment_id": 101}
                fields.pop(missing)
                with transaction.atomic():
                    with self.assertRaises(IntegrityError):
                        Assignment.objects.create(
                            user=self.user, title="Project", course="CS 4300", **fields
                        )

    def test_get_or_create_with_defaults_is_stable(self):
        """Repeated saves reuse one row per (user, Canvas assignment)."""
        first, created = Assignment.objects.get_or_create(
            user=self.user,
            canvas_assignment_id=101,
            defaults={"title": "Canvas Project 1", "course": "CS 4300", "canvas_course_id": 42},
        )
        second, created_again = Assignment.objects.get_or_create(
            user=self.user,
            canvas_assignment_id=101,
            defaults={"title": "Different title", "course": "CS 9999", "canvas_course_id": 999},
        )

        self.assertTrue(created)
        self.assertFalse(created_again)
        self.assertEqual(second.pk, first.pk)
        self.assertEqual(second.title, "Canvas Project 1")

    def test_deleting_user_cascades_to_assignments(self):
        """Deleting an account removes that student's assignments."""
        assignment = Assignment.objects.create(
            canvas_course_id=42, canvas_assignment_id=101,
            user=self.user, title="Project", course="CS 4300"
        )

        self.user.delete()

        self.assertFalse(Assignment.objects.filter(pk=assignment.pk).exists())


@pytest.mark.unit
class StudyFileModelTests(MediaRootTestCase):
    """Study files are user-scoped, collision-free, and reusable."""

    def setUp(self):
        """Every study file in these tests belongs to one student."""
        super().setUp()
        self.user = make_user("file-owner")

    def test_upload_path_is_user_scoped_and_collision_free(self):
        """Two uploads with the same name land in the owner's folder as distinct files."""
        first = upload(self.user, "notes.pdf")
        second = upload(self.user, "notes.pdf")

        expected_dir = Path(self.media_root) / "study_files" / str(self.user.id)
        for study_file in (first, second):
            self.assertEqual(Path(study_file.file.path).parent, expected_dir)
            self.assertTrue(Path(study_file.file.path).exists())
            self.assertTrue(study_file.file.name.endswith(".pdf"))
        self.assertNotEqual(first.file.name, second.file.name)
        self.assertIsNotNone(first.uploaded_at)

    def test_str_returns_original_name(self):
        """The string form is the name the student uploaded, not the uuid path."""
        study_file = upload(self.user, "chapter-1-notes.pdf")

        self.assertEqual(str(study_file), "chapter-1-notes.pdf")

    def test_deleting_user_removes_rows_but_not_stored_files(self):
        """Account deletion cascades the row; the stored bytes are left in place."""
        study_file = upload(self.user, "notes.pdf")
        stored_path = Path(study_file.file.path)

        self.user.delete()

        self.assertFalse(StudyFile.objects.filter(pk=study_file.pk).exists())
        self.assertTrue(stored_path.exists())


@pytest.mark.unit
class AttachmentModelTests(MediaRootTestCase):
    """Attachments link a student's own files to their own assignments."""

    def setUp(self):
        """One student with one assignment and one uploaded study file."""
        super().setUp()
        self.user = make_user("attachment-owner")
        self.assignment = Assignment.objects.create(
            canvas_course_id=42, canvas_assignment_id=101,
            user=self.user, title="Project", course="CS 4300"
        )
        self.study_file = upload(self.user, "notes.pdf")

    def test_links_file_to_assignment_with_blank_category(self):
        """A valid link is queryable from both ends and starts uncategorized."""
        attachment = Attachment.objects.create(
            user=self.user, assignment=self.assignment, study_file=self.study_file
        )

        self.assertEqual(self.assignment.attachments.get(), attachment)
        self.assertEqual(self.study_file.attachments.get(), attachment)
        self.assertEqual(attachment.category, "")

    def test_category_accepts_any_short_label(self):
        """No frozen choices: any string up to 50 characters stores as-is."""
        attachment = Attachment.objects.create(
            user=self.user, assignment=self.assignment,
            study_file=self.study_file, category="Reference",
        )

        self.assertEqual(attachment.category, "Reference")

    def test_one_file_is_reusable_across_assignments(self):
        """The same study file can back several of the student's assignments."""
        other_assignment = Assignment.objects.create(
            canvas_course_id=42, canvas_assignment_id=102,
            user=self.user, title="Essay", course="CS 5000"
        )
        Attachment.objects.create(
            user=self.user, assignment=self.assignment, study_file=self.study_file
        )
        Attachment.objects.create(
            user=self.user, assignment=other_assignment, study_file=self.study_file
        )

        self.assertEqual(self.study_file.attachments.count(), 2)

    def test_duplicate_link_is_rejected(self):
        """The same file cannot be linked to the same assignment twice."""
        Attachment.objects.create(
            user=self.user, assignment=self.assignment, study_file=self.study_file
        )

        with transaction.atomic():
            with self.assertRaises(IntegrityError):
                Attachment.objects.create(
                    user=self.user, assignment=self.assignment,
                    study_file=self.study_file, category="again",
                )

        self.assertEqual(self.assignment.attachments.count(), 1)

    def test_cross_owner_links_are_rejected_on_create(self):
        """Every mismatch permutation of the three users fails with ValidationError."""
        other_user = make_user("other-attachment-owner")
        other_assignment = Assignment.objects.create(
            canvas_course_id=42, canvas_assignment_id=101,
            user=other_user, title="Their project", course="CS 4300"
        )
        other_file = upload(other_user, "their-notes.pdf")
        mismatches = [
            ("link owner only", other_user, self.assignment, self.study_file),
            ("assignment owner only", self.user, other_assignment, self.study_file),
            ("study file owner only", self.user, self.assignment, other_file),
            ("link and assignment owners", other_user, other_assignment, self.study_file),
            ("link and study file owners", other_user, self.assignment, other_file),
            ("assignment and study file owners", self.user, other_assignment, other_file),
        ]

        for label, link_user, assignment, study_file in mismatches:
            with self.subTest(mismatch=label):
                with self.assertRaises(ValidationError):
                    Attachment.objects.create(
                        user=link_user, assignment=assignment, study_file=study_file
                    )

        self.assertFalse(Attachment.objects.exists())

    def test_unlinking_preserves_study_file_and_stored_file(self):
        """Deleting only the link keeps the file record and the bytes on disk."""
        Attachment.objects.create(
            user=self.user, assignment=self.assignment, study_file=self.study_file
        )
        stored_path = Path(self.study_file.file.path)

        Attachment.objects.get(assignment=self.assignment).delete()

        self.assertFalse(Attachment.objects.exists())
        self.assertTrue(StudyFile.objects.filter(pk=self.study_file.pk).exists())
        self.assertTrue(stored_path.exists())
        self.assertTrue(Assignment.objects.filter(pk=self.assignment.pk).exists())

    def test_deleting_assignment_removes_links_but_preserves_study_file(self):
        """Assignment deletion cascades its links only; the file survives."""
        Attachment.objects.create(
            user=self.user, assignment=self.assignment, study_file=self.study_file
        )
        stored_path = Path(self.study_file.file.path)

        self.assignment.delete()

        self.assertFalse(Attachment.objects.exists())
        self.assertTrue(StudyFile.objects.filter(pk=self.study_file.pk).exists())
        self.assertTrue(stored_path.exists())

    def test_deleting_user_cascades_links(self):
        """Deleting the account removes the student's attachments too."""
        Attachment.objects.create(
            user=self.user, assignment=self.assignment, study_file=self.study_file
        )

        self.user.delete()

        self.assertFalse(Attachment.objects.exists())

    def test_str_names_file_and_assignment(self):
        """The string form names the linked file and its assignment."""
        attachment = Attachment.objects.create(
            user=self.user, assignment=self.assignment, study_file=self.study_file
        )

        self.assertEqual(str(attachment), "notes.pdf on Project")
