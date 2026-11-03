"""Integration tests for the course list and course pages."""
from unittest.mock import patch

import pytest
from cryptography.fernet import Fernet
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

# pylint: disable=import-error
from accounts.canvas_client import CanvasAPIError, CanvasAuthenticationError
from accounts.models import CanvasConnection

CURRENT_COURSE = {
    "id": 1,
    "name": "Operating Systems I",
    "term": {"end_at": "2099-01-01T00:00:00Z"},
}
ENDED_COURSE = {
    "id": 2,
    "name": "Programming with UNIX",
    "term": {"end_at": "2000-01-01T00:00:00Z"},
}
FORMATTED_SYLLABUS = (
    "<h4>Grading</h4><ul><li>Quizzes 10%</li></ul>"
    "<table><tr><td>Week 1</td></tr></table><script>alert('x')</script>"
)
FILE_SYLLABUS = (
    '<p>Syllabus: <a class="instructure_file_link" '
    'href="https://canvas.example.edu/courses/1/files/9?wrap=1">syllabus.pdf</a></p>'
)


class ConnectedStudentTestCase(TestCase):
    """A signed-in student with a saved Canvas connection."""

    def setUp(self):
        settings_override = override_settings(
            CANVAS_BASE_URL="https://canvas.example.edu",
            CANVAS_TOKEN_ENCRYPTION_KEY=Fernet.generate_key().decode(),
        )
        settings_override.enable()
        self.addCleanup(settings_override.disable)
        self.user = get_user_model().objects.create_user(username="course-student")
        self.connection = CanvasConnection(user=self.user, canvas_url="https://canvas.example.edu")
        self.connection.set_token("fake-canvas-token")
        self.connection.save()
        self.client.force_login(self.user)


@pytest.mark.integration
class CourseAccessTests(ConnectedStudentTestCase):
    """Course pages are only for signed-in students."""

    def test_signed_out_visitor_is_sent_to_sign_in(self):
        """Both course pages send a signed-out visitor to sign in first."""
        self.client.logout()

        for url in (reverse("course_list"), reverse("course_detail", args=[1])):
            with self.subTest(url=url):
                response = self.client.get(url)

                self.assertRedirects(response, f"{reverse('login')}?next={url}")


@pytest.mark.integration
class CourseListPageTests(ConnectedStudentTestCase):
    """The Courses page lists the student's current Canvas courses."""

    @patch("courses.views.list_courses", return_value=[CURRENT_COURSE, ENDED_COURSE])
    def test_course_list_shows_only_current_courses(self, _list_courses):
        """A course from an ended semester is left out of the list."""
        response = self.client.get(reverse("course_list"))

        self.assertContains(response, "Operating Systems I")
        self.assertNotContains(response, "Programming with UNIX")

    @patch("courses.views.list_courses", return_value=[CURRENT_COURSE])
    def test_course_list_links_to_each_course_page(self, _list_courses):
        """Each listed course opens its own course page."""
        response = self.client.get(reverse("course_list"))

        self.assertContains(response, f'href="{reverse("course_detail", args=[1])}"')

    @patch("courses.views.list_courses", return_value=[ENDED_COURSE])
    def test_no_current_courses_shows_message(self, _list_courses):
        """Only ended courses means an empty list with a clear message."""
        response = self.client.get(reverse("course_list"))

        self.assertContains(response, "No current courses found")

    @patch("courses.views.list_courses")
    def test_missing_connection_asks_to_connect(self, list_courses):
        """Without a saved connection, Canvas is never asked."""
        self.connection.delete()

        response = self.client.get(reverse("course_list"))

        self.assertContains(response, "Connect Canvas to see your courses")
        list_courses.assert_not_called()

    @patch("courses.views.list_courses", side_effect=CanvasAuthenticationError("Rejected"))
    def test_expired_connection_asks_to_reconnect(self, _list_courses):
        """A rejected token is saved as expired and the student is told to reconnect."""
        response = self.client.get(reverse("course_list"))

        self.connection.refresh_from_db()
        self.assertFalse(self.connection.is_valid)
        self.assertContains(response, "Your Canvas connection expired. Please reconnect.")

    @patch("courses.views.list_courses", side_effect=CanvasAPIError("Down"))
    def test_canvas_outage_asks_to_try_again(self, _list_courses):
        """A Canvas outage is not shown as an empty course list."""
        response = self.client.get(reverse("course_list"))

        self.assertContains(response, "Unable to load your courses. Please try again.")
        self.assertNotContains(response, "No current courses found")


@pytest.mark.integration
@patch("courses.views.list_courses", return_value=[CURRENT_COURSE])
class CoursePageTests(ConnectedStudentTestCase):
    """A course page shows that course's syllabus from Canvas."""

    def open_course(self, course_id=1):
        """Open one course page as the signed-in student."""
        return self.client.get(reverse("course_detail", args=[course_id]))

    @patch("courses.views.get_course_syllabus", return_value=FORMATTED_SYLLABUS)
    def test_course_page_shows_cleaned_syllabus(self, _syllabus, _list_courses):
        """The course name heads a syllabus that keeps its formatting but not its script."""
        response = self.open_course()

        self.assertContains(response, "<h1>Operating Systems I</h1>", html=True)
        self.assertContains(response, "<h4>Grading</h4>")
        self.assertContains(response, "<li>Quizzes 10%</li>")
        self.assertContains(response, "<td>Week 1</td>")
        self.assertNotContains(response, "alert(")

    @patch("courses.views.get_course_syllabus", return_value=FORMATTED_SYLLABUS)
    def test_course_page_links_back_to_course_list(self, _syllabus, _list_courses):
        """A student can return to the list of their courses."""
        response = self.open_course()

        self.assertContains(response, f'<a href="{reverse("course_list")}">← All courses</a>')

    @patch("courses.views.get_course_syllabus", return_value=FILE_SYLLABUS)
    def test_syllabus_with_files_shows_preview_notice(self, _syllabus, _list_courses):
        """File names stay readable, a notice explains previews, and nothing links to Canvas."""
        response = self.open_course()

        self.assertContains(response, "syllabus.pdf")
        self.assertContains(response, "File previews are coming soon")
        self.assertNotContains(response, 'href="https://canvas.example.edu')

    @patch("courses.views.get_course_syllabus", return_value=None)
    def test_missing_syllabus_shows_message(self, _syllabus, _list_courses):
        """A course without a syllabus says so instead of showing an empty box."""
        response = self.open_course()

        self.assertContains(response, "No syllabus posted in Canvas for this course")

    @patch("courses.views.get_course_syllabus")
    def test_course_not_in_my_list_is_not_found(self, get_course_syllabus, _list_courses):
        """Only the student's own current courses open, and Canvas is never asked about others."""
        response = self.open_course(999)

        self.assertContains(response, "Course not found", status_code=404)
        get_course_syllabus.assert_not_called()

    @patch("courses.views.get_course_syllabus", side_effect=CanvasAPIError("Down"))
    def test_canvas_outage_asks_to_try_again(self, _syllabus, _list_courses):
        """A Canvas outage is not shown as a missing syllabus."""
        response = self.open_course()

        self.assertContains(response, "Unable to load this course. Please try again.")
        self.assertNotContains(response, "No syllabus posted")
