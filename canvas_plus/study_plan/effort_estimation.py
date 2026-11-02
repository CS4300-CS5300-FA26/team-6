"""AI-assisted effort estimation for student assignments."""

# Import the shared AI inference interface.
from ai_inference.inference import build_content, infer

# Import the structured response model used for effort estimates.
from .schema import EffortEstimate


# Instructions sent to the AI model for every effort-estimation request.
SYSTEM_PROMPT = """
You estimate the amount of focused student work required to complete
a college assignment.

Return a realistic estimate in minutes.

Consider the assignment title, due date, description, and any other
provided assignment information.

Do not assume missing assignment details.

If enough information is provided, return a reasonable positive estimate
and a short explanation for the estimate.
""".strip()


def estimate_assignment_effort(
    title,
    due_date,
    assignment_information,
):
    """Return an AI-generated effort estimate for an assignment.

    Returns None when the assignment does not contain enough information
    to reasonably request an estimate. This allows the application to
    fall back to manual student entry.
    """

    # A title is required so the model knows what assignment
    # it is evaluating.
    if not title or not str(title).strip():
        return None

    # The acceptance criteria specifically call for an assignment
    # with a due date. If one is unavailable, require manual entry.
    if due_date is None:
        return None

    # The AI needs assignment details beyond only a title and due date
    # to make a meaningful effort estimate.
    if not assignment_information or not str(assignment_information).strip():
        return None

    # Build the user-facing prompt from the available assignment data.
    prompt = (
        f"Assignment title: {title}\n"
        f"Due date: {due_date}\n"
        f"Assignment information:\n{assignment_information}\n\n"
        "Estimate the amount of focused work required to complete "
        "this assignment."
    )

    # Convert the prompt into the shared Responses API content format.
    content = build_content(prompt)

    # Use the project's shared AI interface.
    # infer() validates the provider output against EffortEstimate
    # before returning it to us.
    return infer(
        SYSTEM_PROMPT,
        content,
        EffortEstimate,
    )

def has_enough_available_time(estimated_minutes, available_minutes):
    """Return whether the student has enough available study time."""

    # Without an automatic estimate, there is nothing useful to compare.
    if estimated_minutes is None:
        return False

    # Available study time must meet or exceed the required effort.
    return available_minutes >= estimated_minutes
