"""Build structured inference input for study-plan generation."""

import json

from ai_inference import build_content


SYSTEM_PROMPT = """Create a study plan using the supplied assignments and free windows.
Process assignments in earliest-deadline-first order. Schedule sessions only inside
the supplied free windows, without overlapping sessions. Every session must have a
positive duration divisible by 15 minutes. There is no maximum session duration
beyond the available window and deadline constraints. Schedule as much estimated
effort as can fit and report any unscheduled remainder in minutes, identifying the
assignment. Late scheduling is {late_instruction}. Mark each session's late flag
true only when it ends after its assignment deadline.
"""


def build_plan_inference_input(assignments, free_windows, *, allow_late=False):
    """Return the system prompt and user content for a planning inference call.

    Args:
        assignments: Eligible assignment objects, ordered by earliest deadline.
        free_windows: A sequence of aware ``(start, end)`` datetime pairs.
        allow_late: Whether sessions may extend beyond assignment deadlines.
    """
    ordered_assignments = sorted(assignments, key=lambda assignment: assignment.due_date)
    assignment_data = [
        {
            "id": assignment.id,
            "title": assignment.title,
            "course": assignment.course,
            "due_date": _isoformat(assignment.due_date),
            "estimated_minutes": getattr(assignment, "estimated_minutes", None),
        }
        for assignment in ordered_assignments
    ]
    window_data = [
        {"start": _isoformat(start), "end": _isoformat(end)}
        for start, end in free_windows
    ]
    request_data = json.dumps(
        {"assignments": assignment_data, "free_windows": window_data},
        indent=2,
    )
    late_instruction = (
        "allowed when necessary by the request"
        if allow_late
        else "not allowed"
    )
    system_prompt = SYSTEM_PROMPT.format(late_instruction=late_instruction)
    return system_prompt, build_content(request_data)


def _isoformat(value):
    """Serialize datetime-like values consistently in the inference payload."""
    return value.isoformat() if value is not None else None