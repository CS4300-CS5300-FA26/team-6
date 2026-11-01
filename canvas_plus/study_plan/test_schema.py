"""Tests for the structured study-plan response schema."""

from datetime import datetime, timedelta, timezone

import pytest
from openai.lib._pydantic import to_strict_json_schema
from pydantic import ValidationError

from study_plan.schema import StudyPlan


@pytest.mark.unit
def test_valid_payload_parses_as_study_plan():
    """A complete session and notices parse into the response model."""
    payload = {
        "sessions": [
            {
                "assignment_id": 42,
                "start": "2026-11-02T09:00:00-07:00",
                "end": "2026-11-02T10:00:00-07:00",
                "late": False,
            },
        ],
        "notices": ["Assignment 42 has 30 minutes remaining."],
    }

    plan = StudyPlan.model_validate(payload)

    assert len(plan.sessions) == 1
    assert plan.sessions[0].assignment_id == 42
    assert plan.sessions[0].start == datetime(
        2026, 11, 2, 9, 0, tzinfo=timezone(timedelta(hours=-7)),
    )
    assert plan.sessions[0].end == datetime(
        2026, 11, 2, 10, 0, tzinfo=timezone(timedelta(hours=-7)),
    )
    assert plan.sessions[0].late is False
    assert plan.notices == ["Assignment 42 has 30 minutes remaining."]


@pytest.mark.unit
def test_study_plan_generates_a_strict_json_schema():
    """The schema is accepted by the strict schema converter used by inference."""
    schema = to_strict_json_schema(StudyPlan)

    assert schema["type"] == "object"
    assert "sessions" in schema["properties"]
    assert "notices" in schema["properties"]


@pytest.mark.unit
def test_session_missing_required_fields_is_rejected():
    """A session without its end time cannot be treated as a valid proposal."""
    payload = {
        "sessions": [
            {
                "assignment_id": 42,
                "start": "2026-11-02T09:00:00-07:00",
                "late": False,
            },
        ],
        "notices": [],
    }

    with pytest.raises(ValidationError):
        StudyPlan.model_validate(payload)


@pytest.mark.unit
def test_empty_session_list_is_rejected():
    """A schema-valid empty schedule is still not a valid plan."""
    with pytest.raises(ValidationError):
        StudyPlan.model_validate({"sessions": [], "notices": []})
