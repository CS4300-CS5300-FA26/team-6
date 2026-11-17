"""Integration tests for the weekly availability grid's views: URL, view and database together.

The save URL is availability:save_week. It only accepts POST, takes the ticked
blocks as a "block" list, and redirects back to the Study Plan page
(availability:list), whose context carries week_grid. Today is fixed at
Wednesday, November 18, 2020, as in availability_grid.feature.
"""
# Test names say what each test checks, so they carry no docstrings.
# pylint: disable=missing-function-docstring,no-member

from datetime import date, time
from unittest.mock import patch

import pytest
from bs4 import BeautifulSoup
from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from .models import Availability
from .week_grid import GRID_LABELS

pytestmark = pytest.mark.integration

TODAY = date(2020, 11, 18)  # Wednesday
THURSDAY = date(2020, 11, 19)


class GridViewTests(TestCase):
    """A signed-in student on a fixed Wednesday, with no Canvas connection."""

    def setUp(self):
        self.student = get_user_model().objects.create_user(
            username="grid_view_student", password="pw-123456"
        )
        self.client.login(username="grid_view_student", password="pw-123456")
        patcher = patch("django.utils.timezone.localdate", return_value=TODAY)
        patcher.start()
        self.addCleanup(patcher.stop)

    def thursday_periods(self):
        rows = Availability.objects.filter(user=self.student, date=THURSDAY)
        return list(rows.order_by("start_time").values_list("start_time", "end_time"))

    def test_a_save_stores_the_blocks_and_returns_to_the_page(self):
        response = self.client.post(reverse("availability:save_week"), {"block": ["2020-11-19T10"]})

        self.assertRedirects(
            response, reverse("availability:list"), fetch_redirect_response=False
        )
        self.assertEqual(self.thursday_periods(), [(time(10), time(11))])

    def test_a_get_is_refused(self):
        response = self.client.get(reverse("availability:save_week"), {"block": ["2020-11-19T10"]})

        self.assertEqual(response.status_code, 405)
        self.assertEqual(self.thursday_periods(), [])

    def test_a_signed_out_visitor_is_sent_to_sign_in_and_nothing_is_saved(self):
        self.client.logout()

        response = self.client.post(reverse("availability:save_week"), {"block": ["2020-11-19T10"]})

        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.url.startswith(reverse("login")), response.url)
        self.assertFalse(Availability.objects.exists())

    def test_the_page_shows_this_weeks_grid(self):
        response = self.client.get(reverse("availability:list"))

        self.assertEqual(response.status_code, 200)
        grid = response.context["week_grid"]
        self.assertEqual([day["date"] for day in grid], [date(2020, 11, d) for d in range(16, 23)])
        self.assertEqual(response.context["grid_labels"], GRID_LABELS)

    def test_the_grid_form_carries_the_csrf_token_a_browser_sends(self):
        # The test client normally skips CSRF checks; a browser never does.
        browser = Client(enforce_csrf_checks=True)
        browser.login(username="grid_view_student", password="pw-123456")
        page = BeautifulSoup(browser.get(reverse("availability:list")).content, "html.parser")
        form = page.find("input", attrs={"name": "block"}).find_parent("form")
        token = form.find("input", attrs={"name": "csrfmiddlewaretoken"})
        self.assertIsNotNone(token, "the grid form has no CSRF token")

        response = browser.post(
            form["action"], {"csrfmiddlewaretoken": token["value"], "block": ["2020-11-19T10"]}
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.thursday_periods(), [(time(10), time(11))])
