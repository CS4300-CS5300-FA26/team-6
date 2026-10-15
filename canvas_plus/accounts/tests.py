"""Tests for account creation, sign in, and sign out."""
import pytest
from django.contrib.auth import get_user_model
from django.test import TestCase


@pytest.mark.integration
class AccountFlowTests(TestCase):
    """Given a visitor, when they use the account pages, then sessions follow."""

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="student", password="s3cure-Pass-99"
        )

    def test_register_creates_user_and_redirects_to_login(self):
        """A valid registration saves a user with a hashed password."""
        response = self.client.post("/accounts/register/", {
            "username": "newuser",
            "password1": "an0ther-Pass-77",
            "password2": "an0ther-Pass-77",
        })

        self.assertRedirects(response, "/accounts/login/")
        new_user = get_user_model().objects.get(username="newuser")
        self.assertNotEqual(new_user.password, "an0ther-Pass-77")

    def test_register_rejects_mismatched_passwords(self):
        """Mismatched passwords re-render the form and create no user."""
        response = self.client.post("/accounts/register/", {
            "username": "newuser",
            "password1": "an0ther-Pass-77",
            "password2": "different-Pass-11",
        })

        self.assertEqual(response.status_code, 200)
        self.assertFalse(get_user_model().objects.filter(username="newuser").exists())

    def test_login_with_valid_credentials_starts_session(self):
        """Valid credentials log the user in and redirect home."""
        response = self.client.post("/accounts/login/", {
            "username": "student", "password": "s3cure-Pass-99",
        })

        self.assertRedirects(response, "/", fetch_redirect_response=False)
        self.assertEqual(int(self.client.session["_auth_user_id"]), self.user.pk)

    def test_login_with_wrong_password_fails(self):
        """Bad credentials show an error and do not start a session."""
        response = self.client.post("/accounts/login/", {
            "username": "student", "password": "wrong",
        })

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_logout_requires_post_and_ends_session(self):
        """GET is rejected; POST ends the session."""
        self.client.force_login(self.user)

        self.assertEqual(self.client.get("/accounts/logout/").status_code, 405)
        self.client.post("/accounts/logout/")

        self.assertNotIn("_auth_user_id", self.client.session)
