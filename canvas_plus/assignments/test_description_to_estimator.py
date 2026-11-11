"""Canvas HTML descriptions through HTTP normalization to real effort estimation (G7).

Assignment.description is an HTML fragment:
https://developerdocs.instructure.com/services/canvas/resources/assignments
"""
# pylint: disable=import-error
import json
from unittest.mock import patch

import pytest
import requests
from cryptography.fernet import Fernet
from django.contrib.auth import get_user_model
from django.urls import reverse

from accounts.models import CanvasConnection
from assignments.models import Assignment
from study_plan.schema import EffortEstimate


@pytest.mark.django_db
@pytest.mark.parametrize("description_fields", [
    {"description": "<p>Compare <strong>three</strong> primary sources.</p>"},
    {},
    {"description": ""},
], ids=["html-description", "absent-description", "empty-description"])
def test_canvas_description_reaches_effort_estimator_without_inventing_details(
    client, settings, description_fields,
):
    """Given an instructor description or none, when effort opens,
    then estimate only supplied details.
    """
    settings.CANVAS_BASE_URL = "https://canvas.example.edu"
    settings.CANVAS_TOKEN_ENCRYPTION_KEY = Fernet.generate_key().decode()
    user = get_user_model().objects.create_user(username="description-student")
    connection = CanvasConnection(user=user, canvas_url=settings.CANVAS_BASE_URL)
    connection.set_token("test-token")
    connection.save()
    client.force_login(user)
    calls = []

    def get(url, **kwargs):
        params = kwargs.get("params") or {}
        calls.append((url, params))
        if url.endswith("/api/v1/courses"):
            payload = [{"id": 42, "name": "History"}]
        elif url.endswith("/courses/42/assignments"):
            payload = [{
                "id": 101, "name": "Source analysis", "due_at": "2099-01-01T12:00:00Z",
                **description_fields,
            }] if params["bucket"] == "upcoming" else []
        elif url.endswith("/courses/42/students/submissions"):
            payload = []
        else:
            raise AssertionError(f"Unexpected Canvas URL: {url}")
        response = requests.Response()
        response.status_code = 200
        response.headers["Content-Type"] = "application/json"
        response.encoding = "utf-8"
        response._content = json.dumps(payload).encode()  # pylint: disable=protected-access
        return response

    with patch("requests.Session.get", side_effect=get), patch(
        "study_plan.effort_estimation.infer",
        return_value=EffortEstimate(estimated_minutes=90, reason="Three sources to compare."),
    ) as infer:
        response = client.get(reverse("edit_effort_estimate", args=[42, 101]))

    assert infer.call_count == int(bool(description_fields.get("description")))
    assert response.status_code == 200
    assignment = Assignment.objects.get(user=user, canvas_course_id=42, canvas_assignment_id=101)
    if description_fields.get("description"):
        infer.assert_called_once()
        system_prompt, content, schema = infer.call_args.args
        prompt = content[0]["content"][0]["text"]
        assert description_fields["description"] in prompt
        assert "Source analysis" in prompt
        assert "Do not assume missing assignment details." in system_prompt
        assert schema is EffortEstimate
        assert assignment.estimated_effort_minutes == 90
        assert assignment.effort_estimate_source == "automatic"
    else:
        infer.assert_not_called()
        assert assignment.estimated_effort_minutes is None
        assert assignment.effort_estimate_source is None
    assignment_calls = [params for url, params in calls if url.endswith("/assignments")]
    assert {params["bucket"] for params in assignment_calls} == {"upcoming", "overdue"}
    assert all(params["include[]"] == "submission" for params in assignment_calls)
