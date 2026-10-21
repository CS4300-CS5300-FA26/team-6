"""Step definitions for landing_page.feature (card #82), grouped by scenario."""
# The step sentence in each decorator documents the function, so no docstrings.
# pylint: disable=not-callable,missing-function-docstring
from datetime import timedelta

from behave import given, when, then
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from assignments.models import Assignment  # pylint: disable=import-error

LOGGED_IN_HOME = "/assignments/"  # update when the dashboard replaces it
PASSWORD = "Correct-Pass-123"


def page(context):
    return context.response.content.decode()


# Scenario 1: Logged-out visitor sees the landing page

@given("I am not logged in")
def step_not_logged_in(context):
    context.client = Client()


@given('an assignment titled "{title}" exists')
def step_assignment_exists(_context, title):
    due = timezone.now() + timedelta(days=7)
    Assignment.objects.create(title=title, course="CS 4300", due_date=due)


@when("I open the homepage")  # also used by scenario 2
def step_open_homepage(context):
    context.response = context.client.get("/")


@then('I see "{text}"')
def step_see_text(context, text):
    assert text in page(context)


@then("I see a login form")
def step_see_login_form(context):
    assert f'action="{reverse("login")}"' in page(context)
    assert 'name="username"' in page(context)
    assert 'name="password"' in page(context)
    assert 'name="csrfmiddlewaretoken"' in page(context)


@then('the "Register" link points to the registration page')
def step_register_link(context):
    assert f'href="{reverse("register")}"' in page(context)
    assert context.client.get(reverse("register")).status_code == 200


@then('I do not see "{text}"')
def step_not_see_text(context, text):
    assert text not in page(context)


# Scenario 2: Logged-in user skips the landing page

@given("I am logged in")
def step_logged_in(context):
    step_have_account(context)
    context.client.force_login(context.user)


@then("I am taken to my logged-in home page")
def step_redirected_home(context):
    assert context.response.status_code == 302
    assert context.response.url == LOGGED_IN_HOME


# Scenario 3: Logging in from the homepage

@given("I have an account")  # also used by scenarios 2 and 4
def step_have_account(context):
    user_model = get_user_model()
    context.user = user_model.objects.create_user(username="student", password=PASSWORD)
    context.client = Client()


@when("I log in with valid credentials using the form on the homepage")
def step_login_valid(context):
    credentials = {"username": "student", "password": PASSWORD}
    context.response = context.client.post(reverse("login"), credentials, follow=True)


@then("I end up on my logged-in home page")
def step_end_up_home(context):
    assert context.response.redirect_chain[-1][0] == LOGGED_IN_HOME
    assert context.response.wsgi_request.user.is_authenticated


# Scenario 4 (outline): Failed login from the homepage

BAD_LOGINS = {
    "the wrong password": {"username": "student", "password": "Wrong-Pass-999"},
    "an unknown username": {"username": "nobody", "password": PASSWORD},
}


@when("I log in from the homepage with {problem}")
def step_login_bad(context, problem):
    context.response = context.client.post(reverse("login"), BAD_LOGINS[problem])


@then('I am on the login page with the message "{message}"')
def step_on_login_page(context, message):
    assert context.response.request["PATH_INFO"] == reverse("login")
    assert message in page(context)


@then("I am still logged out")
def step_still_logged_out(context):
    assert "_auth_user_id" not in context.client.session
