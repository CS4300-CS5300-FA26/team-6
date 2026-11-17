"""Unit tests for making Canvas syllabus HTML safe to show."""
import pytest

from courses.syllabus import clean_syllabus  # pylint: disable=import-error

CANVAS = "https://canvas.example.edu"


@pytest.mark.unit
def test_scripts_are_removed():
    """A script in the syllabus never reaches the page, but the content around it does."""
    cleaned = clean_syllabus("<h4>Grading</h4><script>alert(1)</script>", CANVAS, 7)

    assert "<h4>Grading</h4>" in cleaned
    assert "<script" not in cleaned
    assert "alert" not in cleaned


@pytest.mark.unit
def test_this_courses_file_links_point_to_canvas_plus():
    """A file in this course links to its Canvas+ viewer instead of Canvas."""
    cleaned = clean_syllabus(
        '<a class="instructure_file_link" title="syllabus.pdf" '
        'href="https://canvas.example.edu/courses/7/files/9?wrap=1">syllabus.pdf</a>',
        CANVAS,
        7,
    )

    assert 'href="/courses/7/files/9/"' in cleaned
    assert 'title="syllabus.pdf"' in cleaned
    assert "canvas.example.edu" not in cleaned


@pytest.mark.unit
@pytest.mark.parametrize("href", [
    "https://canvas.example.edu/courses/7/modules",
    "/courses/7/pages/office-hours",
    "https://canvas.example.edu/courses/8/files/9",
])
def test_other_canvas_links_become_plain_text(href):
    """Links to Canvas pages, or to another course's files, keep their words but lead nowhere."""
    cleaned = clean_syllabus(f'<a href="{href}">Modules</a>', CANVAS, 7)

    assert "Modules" in cleaned
    assert "href" not in cleaned


@pytest.mark.unit
def test_outside_links_open_in_a_new_tab():
    """A professor's own website stays a working link that opens separately."""
    cleaned = clean_syllabus('<a href="https://xu-lab.org/">Prof. Xu</a>', CANVAS, 7)

    assert 'href="https://xu-lab.org/"' in cleaned
    assert 'target="_blank"' in cleaned
    assert 'rel="noopener noreferrer"' in cleaned


@pytest.mark.unit
@pytest.mark.parametrize("html", [None, "", "<p>&nbsp;</p>"])
def test_missing_or_blank_syllabus_cleans_to_nothing(html):
    """No syllabus, or one with no visible text, counts as no syllabus."""
    assert clean_syllabus(html, CANVAS, 7) == ""
