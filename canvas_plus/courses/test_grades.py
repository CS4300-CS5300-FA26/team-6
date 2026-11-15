"""Unit tests for the current grade shown on a course page."""
import pytest

from courses.grades import current_grade  # pylint: disable=import-error


def course_with_grade(score, letter=None):
    """A Canvas course where my student enrollment has this current score and letter."""
    return {
        "hide_final_grades": False,
        "enrollments": [{
            "type": "student",
            "computed_current_score": score,
            "computed_current_grade": letter,
        }],
    }


@pytest.mark.unit
@pytest.mark.parametrize(("score", "letter", "shown"), [
    (97.41, None, "Current grade: 97.41%"),
    (95.69, "A", "Current grade: 95.69% (A)"),
    (0, None, "Current grade: 0%"),
    (100.0, None, "Current grade: 100%"),
    (None, "A", "Current grade: A"),
], ids=["score-only", "score-and-letter", "zero-score", "whole-number-score", "letter-only"])
def test_course_page_shows_my_current_grade(score, letter, shown):
    """Given Canvas has my current grade, when I open the course, then I see it."""
    assert current_grade(course_with_grade(score, letter)) == shown


@pytest.mark.unit
def test_course_with_nothing_graded_says_no_grade_yet():
    """Given nothing is graded yet, when I open the course, then I'm told there's no grade yet."""
    assert current_grade(course_with_grade(None)) == "Current grade: No grade yet"


@pytest.mark.unit
def test_course_with_hidden_total_does_not_show_my_score():
    """Given the instructor hides the course total, when I open the course, then I see no score."""
    course = course_with_grade(97.41, "A")
    course["hide_final_grades"] = True
    assert current_grade(course) == "Your instructor isn't showing a course total"


@pytest.mark.unit
@pytest.mark.parametrize("course", [
    {"hide_final_grades": False, "enrollments": [{"type": "teacher"}]},
    {"hide_final_grades": False, "enrollments": []},
    {"hide_final_grades": False},
], ids=["teacher-only", "no-enrollments", "enrollments-missing"])
def test_course_where_i_am_not_a_student_shows_no_grade(course):
    """Given I'm not enrolled as a student, when I open the course, then no grade line is shown."""
    assert current_grade(course) is None


@pytest.mark.unit
def test_course_with_two_student_enrollments_uses_the_first():
    """Given Canvas lists me twice as a student, when I open the course, then I see the first."""
    course = course_with_grade(88.5)
    course["enrollments"].append(
        {"type": "student", "computed_current_score": 12.0, "computed_current_grade": None}
    )
    assert current_grade(course) == "Current grade: 88.5%"
