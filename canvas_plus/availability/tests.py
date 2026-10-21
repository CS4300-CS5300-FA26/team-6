"""Tests for the availability application."""
# pylint: disable=no-member
#imports test framework, date/time, and forms
from datetime import date, time
from django.test import TestCase
from django.contrib.auth import get_user_model
from django.urls import reverse
from .forms import AvailabilityForm
from .models import Availability

# availability for test class
class AvailabilityFormTests(TestCase):
    """test validation behavior for availability form."""
    def test_valid_availability_is_accepted(self):
        """valid start and end time should pass validation."""
        #create form data end time is after start time.
        form = AvailabilityForm(
            data={
                "date": date(2026, 10, 20),
                "start_time": time(14, 0),
                "end_time": time(16, 0),
            }
        )
        #form should accept availability window.
        self.assertTrue(form.is_valid())

    def test_end_time_before_start_time_is_rejected(self):
        """end time before start time should fail validation."""
        #create form data end time before start time.
        form = AvailabilityForm(
            data={
                "date": date(2026, 10, 20),
                "start_time": time(16, 0),
                "end_time": time(14, 0),
            }
        )

        #form should reject invalid time range
        self.assertFalse(form.is_valid())
        #student receives error message
        self.assertIn(
            "End time must be later than start time.",
            form.non_field_errors(),
        )

class AvailabilityViewTests(TestCase):
    """Test creating, viewing, and editing student availability."""

    def setUp(self):
        #Create a user and log them in before each view test.
        # Get the User model.
        user_model = get_user_model()

        # Create a test student account.
        self.user = user_model.objects.create_user(
            username="availability_student",
            password="test-password-123",
        )

        # Log the test client in as that student.
        self.client.login(
            username="availability_student",
            password="test-password-123",
        )

    def test_student_can_create_valid_availability(self):
        """A student should be able to save valid availability."""
        #Submit a valid availability window to main page.
        response = self.client.post(
            reverse("availability:list"),
            {
                "date": "2026-10-20",
                "start_time": "14:00",
                "end_time": "16:00",
            },
        )

        #A successful save redirects back to the availability page.
        self.assertRedirects(
            response,
            reverse("availability:list"),
        )

        # Confirms the availability record was saved.
        availability = Availability.objects.get(user=self.user)

        self.assertEqual(
            availability.date,
            date(2026, 10, 20),
        )
        self.assertEqual(
            availability.start_time,
            time(14, 0),
        )
        self.assertEqual(
            availability.end_time,
            time(16, 0),
        )

    def test_saved_availability_appears_on_page(self):
        """Saved availability should appear in the availability section."""
        #Create an availability record in the test database.
        Availability.objects.create(
            user=self.user,
            date=date(2026, 10, 20),
            start_time=time(14, 0),
            end_time=time(16, 0),
        )

        # Request the main availability page.
        response = self.client.get(
            reverse("availability:list")
        )

        # Confirm the page loads successfully.
        self.assertEqual(response.status_code, 200)

        # Confirm the saved date appears in the rendered page.
        self.assertContains(
            response,
            "Oct. 20, 2026",
        )

    def test_student_can_change_existing_availability(self):
        """A student should be able to update saved availability"""
        #Create an existing availability entry.
        availability = Availability.objects.create(
            user=self.user,
            date=date(2026, 10, 20),
            start_time=time(14, 0),
            end_time=time(16, 0),
        )

        # Submit updated values to the edit page.
        response = self.client.post(
            reverse(
                "availability:edit",
                args=[availability.id],
            ),
            {
                "date": "2026-10-21",
                "start_time": "15:00",
                "end_time": "17:00",
            },
        )

        # A successful edit should redirect back to main page.
        self.assertRedirects(
            response,
            reverse("availability:list"),
        )

        # Reload the record from the database.
        availability.refresh_from_db()

        # Confirm the changed values were saved.
        self.assertEqual(
            availability.date,
            date(2026, 10, 21),
        )
        self.assertEqual(
            availability.start_time,
            time(15, 0),
        )
        self.assertEqual(
            availability.end_time,
            time(17, 0),
        )

    def test_invalid_availability_is_not_saved(self):
        """An invalid time range should be rejected and not saved"""
        #Submit an end time that comes before the start time.
        response = self.client.post(
            reverse("availability:list"),
            {
                "date": "2026-10-20",
                "start_time": "16:00",
                "end_time": "14:00",
            },
        )

        #Invalid form submissions should render the same page again.
        self.assertEqual(response.status_code, 200)

        # Confirm no invalid availability record was saved.
        self.assertFalse(
            Availability.objects.filter(user=self.user).exists()
        )

        # Confirm the correction message is shown to the student.
        self.assertContains(
            response,
            "End time must be later than start time.",
        )

    def test_anonymous_user_cannot_access_availability_page(self):
        """An anonymous user gets redirected away."""

        # Log out the test user created in setUp().
        self.client.logout()

        # Attempt to access the protected availability page.
        response = self.client.get(
            reverse("availability:list")
        )

        # login_required should redirect the anonymous user.
        self.assertEqual(response.status_code, 302)

        # Confirm the redirect is pointing toward the login page.
        self.assertIn("/login", response.url)

    def test_student_cannot_see_another_users_availability(self):
        """Students cannot see others availability."""

        # Get configured user model.
        user_model = get_user_model()

        # Create another student account.
        other_user = user_model.objects.create_user(
            username="other_student",
            password="other-password-123",
        )

        # Create availability owned by the other student.
        Availability.objects.create(
            user=other_user,
            date=date(2026, 10, 22),
            start_time=time(10, 0),
            end_time=time(12, 0),
        )

        # Request the availability page while still logged in as original test user.
        response = self.client.get(
            reverse("availability:list")
        )

        # Confirm the page itself loads successfully.
        self.assertEqual(response.status_code, 200)

        # Confirm the other student's availability does not appear.
        self.assertNotContains(
            response,
            "Oct. 22, 2026",
        )

    def test_student_cannot_edit_another_users_availability(self):
        """Student's can't edit another user's availability."""

        # Get configured user model.
        user_model = get_user_model()

        # Create another student account.
        other_user = user_model.objects.create_user(
            username="protected_student",
            password="other-password-123",
        )

        # Create availability owned by the other student.
        other_availability = Availability.objects.create(
            user=other_user,
            date=date(2026, 10, 22),
            start_time=time(10, 0),
            end_time=time(12, 0),
        )

        # Try to open the other student's edit page.
        response = self.client.get(
            reverse(
                "availability:edit",
                args=[other_availability.id],
            )
        )

        # The view should behave as though the record does not exist.
        self.assertEqual(response.status_code, 404)

    def test_invalid_edit_is_rejected(self):
        """Invalid edited time range can't replace valid saved data."""

        # Create a valid existing availability entry.
        availability = Availability.objects.create(
            user=self.user,
            date=date(2026, 10, 20),
            start_time=time(14, 0),
            end_time=time(16, 0),
        )

        # Submit an invalid edit where the end time is before the start time.
        response = self.client.post(
            reverse(
                "availability:edit",
                args=[availability.id],
            ),
            {
                "date": "2026-10-20",
                "start_time": "16:00",
                "end_time": "14:00",
            },
        )

        # Invalid input should re-render the edit page.
        self.assertEqual(response.status_code, 200)

        # Confirm the validation message is shown.
        self.assertContains(
            response,
            "End time must be later than start time.",
        )

        # Reload the saved record from the database.
        availability.refresh_from_db()

        # Confirm the original valid values were preserved.
        self.assertEqual(
            availability.start_time,
            time(14, 0),
        )
        self.assertEqual(
            availability.end_time,
            time(16, 0),
        )
