"""Tests for validating AI-proposed study sessions."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from study_plan.validation import PlanValidationError, validate_plan


UTC = timezone.utc
START = datetime(2026, 11, 2, 9, 0, tzinfo=UTC)
DEADLINE = START + timedelta(hours=3)
AVAILABILITY = [(START, DEADLINE)]
ASSIGNMENT_DEADLINES = {42: DEADLINE}


def make_session(assignment_id=42, start=START, end=None, late=False):
    """Build a session proposal with a convenient default duration."""
    return SimpleNamespace(
        assignment_id=assignment_id,
        start=start,
        end=end if end is not None else start + timedelta(minutes=30),
        late=late,
    )


def make_plan(*sessions):
    """Build a minimal plan object accepted by the validator."""
    return SimpleNamespace(sessions=list(sessions), notices=[])


def assert_plan_rejected(
    plan,
    *,
    availability_windows=AVAILABILITY,
    assignment_deadlines=ASSIGNMENT_DEADLINES,
    occupied_sessions=(),
    allow_late=False,
):
    """Assert a proposal violates a scheduling rule."""
    with pytest.raises(PlanValidationError):
        validate_plan(
            plan,
            assignment_deadlines,
            availability_windows,
            occupied_sessions=occupied_sessions,
            allow_late=allow_late,
        )


@pytest.mark.unit
@pytest.mark.parametrize(
    ("duration", "valid"),
    [
        pytest.param(0, False, id="zero-minutes"),
        pytest.param(15, True, id="15-minutes"),
        pytest.param(30, True, id="30-minutes"),
        pytest.param(45, True, id="45-minutes"),
        pytest.param(60, True, id="60-minutes"),
        pytest.param(90, True, id="over-60-minutes"),
        pytest.param(20, False, id="not-a-15-minute-multiple"),
    ],
)
def test_session_duration_must_be_a_positive_multiple_of_fifteen(duration, valid):
    """Positive 15-minute multiples have no maximum; other durations are invalid."""
    proposed = make_session(end=START + timedelta(minutes=duration))
    plan = make_plan(proposed)

    if valid:
        result = validate_plan(
            plan,
            ASSIGNMENT_DEADLINES,
            AVAILABILITY,
        )
        assert result.sessions == [proposed]
    else:
        assert_plan_rejected(plan)


@pytest.mark.unit
def test_session_outside_availability_is_rejected():
    """A session must fit entirely inside an available window."""
    proposed = make_session(
        start=START - timedelta(minutes=15),
        end=START + timedelta(minutes=15),
    )

    assert_plan_rejected(make_plan(proposed))


@pytest.mark.unit
def test_overlapping_sessions_in_same_plan_are_rejected():
    """Sessions in one proposal may not overlap each other."""
    first = make_session(start=START, end=START + timedelta(minutes=45))
    second = make_session(
        start=START + timedelta(minutes=30),
        end=START + timedelta(minutes=60),
    )

    assert_plan_rejected(make_plan(first, second))


@pytest.mark.unit
def test_session_overlapping_earlier_plan_is_rejected():
    """A new session may not overlap time consumed by an earlier plan."""
    occupied = [(START + timedelta(minutes=30), START + timedelta(minutes=60))]
    proposed = make_session(
        start=START + timedelta(minutes=15),
        end=START + timedelta(minutes=45),
    )

    assert_plan_rejected(
        make_plan(proposed),
        occupied_sessions=occupied,
    )


@pytest.mark.unit
def test_session_past_deadline_without_late_opt_in_is_rejected():
    """A session after its assignment deadline requires explicit opt-in."""
    proposed = make_session(
        start=DEADLINE - timedelta(minutes=15),
        end=DEADLINE + timedelta(minutes=15),
        late=True,
    )

    assert_plan_rejected(
        make_plan(proposed),
        availability_windows=[(START, DEADLINE + timedelta(hours=1))],
    )


@pytest.mark.unit
def test_unknown_assignment_id_is_rejected():
    """Every session must refer to an assignment included in the request."""
    assert_plan_rejected(make_plan(make_session(assignment_id=99)))


@pytest.mark.unit
def test_empty_session_list_is_rejected():
    """A plan with no proposed sessions is invalid."""
    assert_plan_rejected(make_plan())


@pytest.mark.unit
def test_session_ending_exactly_at_deadline_is_accepted():
    """A session ending at the deadline is valid when other rules pass."""
    proposed = make_session(
        start=DEADLINE - timedelta(minutes=60),
        end=DEADLINE,
    )

    result = validate_plan(
        make_plan(proposed),
        ASSIGNMENT_DEADLINES,
        AVAILABILITY,
    )

    assert result.sessions == [proposed]


@pytest.mark.unit
@pytest.mark.parametrize(
    ("allow_late", "late"),
    [
        pytest.param(False, True, id="no-opt-in"),
        pytest.param(True, False, id="late-flag-missing"),
    ],
)
def test_late_session_requires_opt_in_and_late_flag(allow_late, late):
    """Late proposals need both request opt-in and an explicit late flag."""
    proposed = make_session(
        start=DEADLINE,
        end=DEADLINE + timedelta(minutes=30),
        late=late,
    )

    assert_plan_rejected(
        make_plan(proposed),
        availability_windows=[(START, DEADLINE + timedelta(hours=1))],
        allow_late=allow_late,
    )


@pytest.mark.unit
def test_late_session_with_opt_in_and_late_flag_is_accepted():
    """An explicitly enabled late proposal is accepted and remains labeled late."""
    proposed = make_session(
        start=DEADLINE,
        end=DEADLINE + timedelta(minutes=30),
        late=True,
    )

    result = validate_plan(
        make_plan(proposed),
        ASSIGNMENT_DEADLINES,
        [(START, DEADLINE + timedelta(hours=1))],
        allow_late=True,
    )

    assert result.sessions == [proposed]
    assert result.sessions[0].late is True
