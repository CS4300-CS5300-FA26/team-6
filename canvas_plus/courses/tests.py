"""Integration tests for the course list and course pages."""
from unittest.mock import patch

import pytest
from cryptography.fernet import Fernet
from django.contrib.auth import get_user_model
from django.conf import settings
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse

# pylint: disable=import-error
from accounts.canvas_client import CanvasAPIError, CanvasAuthenticationError
from accounts.models import CanvasConnection
from courses.test_hub_helpers import (
    HUB_NOW,
    active_hub_courses,
    course_links,
    excluded_hub_courses,
    hub_cache_clock,
    hub_course,
    hub_day_groups,
    hub_week_assignments,
    install_hub_canvas,
    upcoming_section,
)

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

    @patch("courses.views.get_course_syllabus")
    def test_missing_connection_asks_to_connect(self, get_course_syllabus, list_courses):
        """Without a saved connection, the course page asks to connect and Canvas is never asked."""
        self.connection.delete()

        response = self.open_course()

        self.assertContains(response, "Connect Canvas to see your courses")
        list_courses.assert_not_called()
        get_course_syllabus.assert_not_called()

    def test_expired_connection_asks_to_reconnect(self, list_courses):
        """A rejected token is saved as expired and the student is told to reconnect."""
        list_courses.side_effect = CanvasAuthenticationError("Rejected")

        response = self.open_course()

        self.connection.refresh_from_db()
        self.assertFalse(self.connection.is_valid)
        self.assertContains(response, "Your Canvas connection expired. Please reconnect.")

    @patch("courses.views.get_course_syllabus", side_effect=CanvasAPIError("Down"))
    def test_canvas_outage_asks_to_try_again(self, _syllabus, _list_courses):
        """A Canvas outage is not shown as a missing syllabus."""
        response = self.open_course()

        self.assertContains(response, "Unable to load this course. Please try again.")
        self.assertNotContains(response, "No syllabus posted")


@pytest.mark.integration
class CourseHubTests(ConnectedStudentTestCase):
    """Issue #137: course navigation and coursework on the existing Courses pages."""

    def setUp(self):
        super().setUp()
        self.active_courses = active_hub_courses()
        self.excluded_courses = excluded_hub_courses()
        self.canvas = install_hub_canvas(
            self.addCleanup, self.active_courses + self.excluded_courses,
        )

    def test_dashboard_has_one_short_code_tab_per_active_course(self):
        """Every active course has exactly one link labeled with its Canvas short code."""
        response = self.client.get(reverse("course_list"))

        self.assertEqual(response.status_code, 200)
        links = course_links(response, self.canvas.courses)
        self.assertCountEqual(
            [(link["href"], link.get_text(strip=True)) for link in links],
            [(reverse("course_detail", args=[course["id"]]), course["course_code"])
             for course in self.active_courses],
        )

    def test_stale_and_inactive_courses_are_absent_from_dashboard(self):
        """Ended terms and nonactive student enrollments never appear on the Hub."""
        response = self.client.get(reverse("course_list"))

        self.assertEqual(response.status_code, 200)
        for course in self.excluded_courses:
            with self.subTest(course=course["name"]):
                self.assertNotContains(response, course["name"])
                self.assertNotContains(response, course["course_code"])
                self.assertNotContains(
                    response, f'href="{reverse("course_detail", args=[course["id"]])}"',
                )

    def test_stale_and_inactive_courses_have_no_course_page(self):
        """Direct URLs cannot bypass the active-course restriction."""
        for course in self.excluded_courses:
            with self.subTest(course=course["name"]):
                response = self.client.get(reverse("course_detail", args=[course["id"]]))
                self.assertContains(response, "Course not found", status_code=404)

    def test_each_tab_opens_the_course_identified_by_canvas(self):
        """Follow each actual tab link and verify the destination's full course heading."""
        response = self.client.get(reverse("course_list"))
        links = course_links(response, self.canvas.courses)
        for course in self.active_courses:
            with self.subTest(course=course["course_code"]):
                matching = [link for link in links
                            if link.get_text(strip=True) == course["course_code"]]
                self.assertEqual(len(matching), 1)
                self.assertEqual(matching[0]["href"], reverse("course_detail", args=[course["id"]]))
                destination = self.client.get(matching[0]["href"])
                self.assertContains(destination, f'<h1>{course["name"]}</h1>', html=True)

    def test_course_page_shows_only_its_upcoming_assignments(self):
        """Each course shows its own work and hides work belonging to every other course."""
        for course in self.active_courses:
            with self.subTest(course=course["course_code"]):
                response = self.client.get(reverse("course_detail", args=[course["id"]]))
                for course_id, assignments in self.canvas.assignments.items():
                    for assignment in assignments:
                        if course_id == course["id"]:
                            self.assertContains(response, assignment["name"])
                        else:
                            self.assertNotContains(response, assignment["name"])

    def test_dashboard_shows_upcoming_assignments_from_all_active_courses(self):
        """The Hub combines current coursework while excluding stale or inactive coursework."""
        response = self.client.get(reverse("course_list"))

        for course in self.active_courses:
            self.assertContains(response, self.canvas.assignments[course["id"]][0]["name"])
        for course in self.excluded_courses:
            self.assertNotContains(response, self.canvas.assignments[course["id"]][0]["name"])

    def test_zero_active_courses_keeps_existing_empty_message(self):
        """An account with only stale or inactive courses retains the current empty state."""
        self.canvas.courses = self.excluded_courses

        response = self.client.get(reverse("course_list"))

        self.assertContains(response, "No current courses found")
        self.assertEqual(course_links(response, self.excluded_courses), [])

    def test_dashboard_caps_course_tabs_at_twenty(self):
        """Twenty-one active courses yield twenty distinct course links, without fixing order."""
        self.canvas.courses = [hub_course(50000 + index, f"CS {index}", f"Course {index}")
                               for index in range(21)]

        response = self.client.get(reverse("course_list"))

        self.assertEqual(response.status_code, 200)
        links = course_links(response, self.canvas.courses)
        self.assertEqual(len(links), 20)
        self.assertEqual(len({link["href"] for link in links}), 20)

    @override_settings(CACHES=settings.LOCMEM_CACHE)
    def test_dashboard_reuses_course_cache_for_one_hour(self):
        """The shared course key survives 59:59, then expires after the one-hour TTL."""
        cache.clear()
        self.addCleanup(cache.clear)
        # Django resolves this model field to a datetime on saved instances.
        # pylint: disable-next=no-member
        key = f"canvas-courses:{self.connection.pk}:{self.connection.updated_at.timestamp()}"
        clock = hub_cache_clock(self.addCleanup)
        first = self.client.get(reverse("course_list"))
        self.assertEqual(first.status_code, 200)
        self.assertEqual(self.canvas.course_calls, 1)
        clock.return_value += 3599
        second = self.client.get(reverse("course_list"))
        self.assertEqual(second.status_code, 200)
        self.assertEqual(self.canvas.course_calls, 1)
        self.assertIsNotNone(cache.get(key))
        clock.return_value += 2
        third = self.client.get(reverse("course_list"))
        self.assertEqual(third.status_code, 200)
        self.assertEqual(self.canvas.course_calls, 2)

    @override_settings(CACHES=settings.LOCMEM_CACHE)
    def test_dashboard_reads_existing_assignments_page_course_cache(self):
        """A course list cached under the assignments-page key prevents a Canvas courses call."""
        cache.clear()
        self.addCleanup(cache.clear)
        # Django resolves this model field to a datetime on saved instances.
        # pylint: disable-next=no-member
        key = f"canvas-courses:{self.connection.pk}:{self.connection.updated_at.timestamp()}"
        cache.set(key, self.active_courses, 3600)

        response = self.client.get(reverse("course_list"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.canvas.course_calls, 0)
        self.assertEqual(len(course_links(response, self.canvas.courses)), len(self.active_courses))


@pytest.mark.integration
@override_settings(TIME_ZONE="America/Denver")
class CourseHubFocusedListTests(ConnectedStudentTestCase):
    """Option A: the hub lists this week's work by local due day."""

    def setUp(self):
        super().setUp()
        self.active_courses = active_hub_courses()
        self.canvas = install_hub_canvas(self.addCleanup, self.active_courses)
        self.canvas.assignments = hub_week_assignments(self.active_courses)
        clock = patch("django.utils.timezone.now", return_value=HUB_NOW)
        clock.start()
        self.addCleanup(clock.stop)

    def test_dashboard_groups_this_weeks_work_by_local_due_day(self):
        """Chips, titles, course names and due times sit under each local day header."""
        response = self.client.get(reverse("course_list"))

        self.assertEqual(hub_day_groups(response), [
            ("Today · Wed Nov 11", [
                ("CS 4300", "Sprint 4 retrospective", "Software Engineering", "11:59 PM"),
            ]),
            ("Thursday · Nov 12", [
                ("MATH 2150", "Problem set 7", "Discrete Mathematics", "9:00 AM"),
                ("ENGL 1310", "Annotated bibliography draft", "Rhetoric and Writing", "11:59 PM"),
            ]),
            ("Monday · Nov 16", [
                ("HIST 1010", "Reading response: Silk Road trade", "World History", "5:00 PM"),
            ]),
        ])

    def test_dashboard_header_names_its_scope(self):
        """The header names the list and says it covers all courses for 7 days."""
        section = upcoming_section(self.client.get(reverse("course_list")))

        self.assertEqual(section.find("h2").get_text(strip=True), "Upcoming assignments")
        self.assertIn("All courses · next 7 days", section.get_text(" ", strip=True))

    def test_dashboard_leaves_out_work_outside_the_next_seven_days(self):
        """Overdue work stays on the assignments page, not the hub."""
        response = self.client.get(reverse("course_list"))

        self.assertNotContains(response, "Sprint 3 demo")

    def test_dashboard_links_to_every_upcoming_assignment(self):
        """The link counts all upcoming work, including what the 7-day list leaves out."""
        section = upcoming_section(self.client.get(reverse("course_list")))

        link = section.find("a", href=reverse("assignment_list"))
        self.assertIsNotNone(link)
        self.assertEqual(link.get_text(strip=True), "View all 5 assignments →")

    def test_empty_week_says_so_and_still_links_to_all_work(self):
        """With only overdue work, the hub says nothing is due and points to the full list."""
        self.canvas.assignments = {
            course_id: [a for a in assignments if a["name"] == "Sprint 3 demo"]
            for course_id, assignments in self.canvas.assignments.items()
        }

        section = upcoming_section(self.client.get(reverse("course_list")))

        self.assertIn("No assignments due in the next 7 days", section.get_text(" ", strip=True))
        self.assertEqual(section.find("a", href=reverse("assignment_list")).get_text(strip=True),
                         "View all 1 assignment →")

    def test_unavailable_assignments_show_no_view_all_link(self):
        """A failed assignments load can't report a count, so the link is left out."""
        with patch("courses.views.list_upcoming_assignments",
                   side_effect=CanvasAPIError("down")):
            response = self.client.get(reverse("course_list"))

        self.assertContains(response, "Unable to load upcoming assignments. Please try again.")
        # The sidebar also links there, so look only inside the assignments section.
        self.assertIsNone(upcoming_section(response).find("a", href=reverse("assignment_list")))

    def test_course_page_has_no_hub_scope_or_view_all_link(self):
        """A course page lists its own work by day without the hub's scope line or link."""
        software = self.active_courses[0]

        response = self.client.get(reverse("course_detail", args=[software["id"]]))

        section = upcoming_section(response)
        self.assertNotIn("All courses", section.get_text(" ", strip=True))
        self.assertIsNone(section.find("a", href=reverse("assignment_list")))
        self.assertEqual([title for _, cards in hub_day_groups(response)
                          for _, title, _, _ in cards],
                         ["Sprint 3 demo", "Sprint 4 retrospective"])
