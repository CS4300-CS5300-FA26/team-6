"""Tests for account creation, sign in, and sign out."""
import pytest
from django.contrib.auth import get_user_model
from django.test import TestCase, Client


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
        self.assertTrue(get_user_model().objects.filter(username="newuser").exists())
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

    def test_register_rejects_missing_fields(self):
        """Missing required fields re-render the form and create no user."""
        cases = [ # username, password1, password2
            ("", "", ""),
            ("fake_name", "password", ""),
            ("another_fake", "", "password"),
            ("", "password", "password")
        ]
        for username, password1, password2 in cases:
            with self.subTest(username=username, password1=password1, password2=password2):
                response = self.client.post("/accounts/register/", {
                    "username": username,
                    "password1": password1,
                    "password2": password2,
                })

                self.assertEqual(response.status_code, 200)
                self.assertFalse(
                    get_user_model().objects.filter(username=username).exists()
                )

    def test_register_rejects_incomplex_passwords(self):
        """Incomplex passwords re-render the form and create no user."""
        cases = [ # username, password
            ("newuser", "password"),
            ("anotheruser", "12345678"),
            ("yetanother", "$sh0rt"),
        ]
        for username, password in cases:
            with self.subTest(username=username, password=password):
                response = self.client.post("/accounts/register/", {
                    "username": username,
                    "password1": password,
                    "password2": password,
                })

                self.assertEqual(response.status_code, 200)
                self.assertFalse(
                    get_user_model().objects.filter(username=username).exists()
                )

    def test_register_rejects_duplicate_usernames(self):
        """Duplicate usernames re-render the form and create no user."""
        get_user_model().objects.create_user(username="existinguser", password="s3cure-Pass-99")

        response = self.client.post("/accounts/register/", {
            "username": "existinguser",
            "password1": "Another-Pass-88",
            "password2": "Another-Pass-88",
        })

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            get_user_model().objects.filter(username="existinguser").count(),
            1
        )

    def test_register_stores_hash_password(self):
        """Passwords are stored as hashes, not plain text."""
        username = "newuser"
        password = "s3cure-Pass-99"
        self.client.post("/accounts/register/", {
            "username": username,
            "password1": password,
            "password2": password,
        })
        user = get_user_model().objects.get(username=username)
        self.assertNotEqual(user.password, password)
        self.assertTrue(user.check_password(password))

    def test_register_rejects_post_without_csrf_token(self):
        """A POST without a CSRF token is rejected and creates no user."""
        client = Client(enforce_csrf_checks=True)

        response = client.post("/accounts/register/", {
            "username": "newuser",
            "password1": "an0ther-Pass-77",
            "password2": "an0ther-Pass-77",
        })

        self.assertEqual(response.status_code, 403)
        self.assertFalse(get_user_model().objects.filter(username="newuser").exists())

    def test_register_accepts_post_with_csrf_token(self):
        """A POST with a valid CSRF token succeeds."""
        client = Client(enforce_csrf_checks=True)
        token = client.get("/accounts/register/").context["csrf_token"]

        response = client.post("/accounts/register/", {
            "username": "newuser",
            "password1": "an0ther-Pass-77",
            "password2": "an0ther-Pass-77",
            "csrfmiddlewaretoken": token,
        })

        self.assertRedirects(response, "/accounts/login/")
        self.assertNotEqual(response.status_code, 403)
        self.assertEqual(response.status_code, 302)

    def test_register_page_renders_form(self):
        """GET shows the registration form."""
        response = self.client.get("/accounts/register/")

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "accounts/register.html")

    def test_login_with_valid_credentials_starts_session(self):
        """Valid credentials log the user in and starts the session"""
        response = self.client.post("/accounts/login/", {
            "username": "student", "password": "s3cure-Pass-99",
        })

        self.assertEqual(int(self.client.session["_auth_user_id"]), self.user.pk)

    def test_login_with_wrong_password_fails(self):
        """Bad credentials show an error and do not start a session."""
        response = self.client.post("/accounts/login/", {
            "username": "student", "password": "wrong",
        })

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_login_with_nonexistent_user_fails(self):
        """Logging in with a username that doesn't exist shows an error and does not start a session."""
        response = self.client.post("/accounts/login/", {
            "username": "nonexistent", "password": "doesntmatter",
        })

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_login_with_blank_fields_fails(self):
        """Logging in with blank username or password shows an error and does not start a session."""
        response = self.client.post("/accounts/login/", {
            "username": "", "password": "",
        })

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_login_page_renders_form(self):
        """GET shows the login form."""
        response = self.client.get("/accounts/login/")

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "accounts/login.html")

    def test_login_ignores_untrusted_next_urls(self):
        """External or scheme-based 'next' values never become the redirect target."""
        cases = [
            "https://evil.example/",
            "//evil.example/",
            "/\\evil.example",
            "javascript:alert(1)",
        ]
        for next_url in cases:
            with self.subTest(next=next_url):
                response = self.client.post("/accounts/login/", {
                    "next": next_url,
                    "username": "student",
                    "password": "s3cure-Pass-99",
                }, QUERY_STRING=f"next={next_url}")

                self.assertRedirects(response, "/", fetch_redirect_response=False)
                self.client.logout()

    def test_login_redirects_to_next_when_trusted(self):
        """Login redirects to the 'next' URL if it is a trusted local URL."""
        next_url = "/some/local/path/"
        response = self.client.post("/accounts/login/", {
            "username": "student",
            "password": "s3cure-Pass-99",
            "next": next_url,
        }, QUERY_STRING=f"next={next_url}")

        self.assertRedirects(response, next_url, fetch_redirect_response=False)

    def test_login_failures_do_not_display_password(self):
        """Failed login attempts do not reveal sensitive information in the response."""
        response = self.client.post("/accounts/login/", {
            "username": "student", "password": "wrong-password",
        })

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("s3cure-Pass-99", response.content.decode())

    def test_login_failures_do_not_reveal_account_existence(self):
        """Failed logins give the same error for existing and nonexistent users."""
        wrong_password = self.client.post("/accounts/login/", {
            "username": "student", "password": "wrong-password",
        })
        nonexistent_user = self.client.post("/accounts/login/", {
            "username": "nonexistent", "password": "wrong-password",
        })

        self.assertEqual(wrong_password.status_code, 200)
        self.assertEqual(nonexistent_user.status_code, 200)
        self.assertEqual(
            list(wrong_password.context["form"].non_field_errors()),
            list(nonexistent_user.context["form"].non_field_errors()),
        )
        content = nonexistent_user.content.decode().lower()
        for phrase in ("does not exist", "doesn't exist", "no account", "not found", "unknown user"):
            self.assertNotIn(phrase, content)

    def test_login_rejects_post_without_csrf_token(self):
        """POST requests without a CSRF token are rejected."""
        client = Client(enforce_csrf_checks=True)
        response = client.post("/accounts/login/", {
            "username": "student",
            "password": "s3cure-Pass-99",
        })
        self.assertEqual(response.status_code, 403)
        self.assertIn("CSRF", response.content.decode())

    def test_login_accepts_post_with_csrf_token(self):
        """POST requests with a valid CSRF token are accepted."""
        client = Client(enforce_csrf_checks=True)
        token = client.get("/accounts/register/").context["csrf_token"]

        response = client.post("/accounts/login/", {
            "username": "student",
            "password": "s3cure-Pass-99",
            "csrfmiddlewaretoken": token,
        })
        self.assertNotEqual(response.status_code, 403)
        self.assertEqual(response.status_code, 302)

    def test_logout_requires_post_and_ends_session(self):
        """GET is rejected; POST ends the session."""
        self.client.force_login(self.user)

        self.assertEqual(self.client.get("/accounts/logout/").status_code, 405)
        self.client.post("/accounts/logout/")

        self.assertNotIn("_auth_user_id", self.client.session)

    def test_logout_rejects_post_without_csrf_token(self):
        """POST requests to logout without a CSRF token are rejected."""
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)

        response = client.post("/accounts/logout/")

        self.assertEqual(response.status_code, 403)
        self.assertIn("CSRF", response.content.decode())

    def test_logout_accepts_post_with_csrf_token(self):
        """POST requests to logout with a valid CSRF token are accepted."""
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)
        token = client.get("/accounts/register/").context["csrf_token"]

        response = client.post("/accounts/logout/", {
            "csrfmiddlewaretoken": token,
        })
        self.assertNotEqual(response.status_code, 403)
        self.assertEqual(response.status_code, 302)
