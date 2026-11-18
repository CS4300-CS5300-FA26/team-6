"""The current grade shown on a course page, taken from Canvas's own course total."""


def current_grade(course):
    """The grade line for my student enrollment in a Canvas course, or None if I'm not a student."""
    enrollment = next(
        (e for e in course.get("enrollments") or [] if e.get("type") == "student"), None
    )
    if enrollment is None:
        return None
    if course.get("hide_final_grades"):
        return "Your instructor isn't showing a course total"
    score = enrollment.get("computed_current_score")
    letter = enrollment.get("computed_current_grade")
    if score is None:
        return f"Current grade: {letter or 'No grade yet'}"
    shown = f"{round(score, 2):g}%"
    return f"Current grade: {shown} ({letter})" if letter else f"Current grade: {shown}"
