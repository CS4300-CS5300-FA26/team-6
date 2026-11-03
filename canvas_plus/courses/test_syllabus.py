"""Unit tests for making Canvas syllabus HTML safe to show."""
import pytest

from courses.syllabus import clean_syllabus  # pylint: disable=import-error

CANVAS = "https://canvas.example.edu"


@pytest.mark.unit
def test_scripts_are_removed():
    """A script in the syllabus never reaches the page, but the content around it does."""
    cleaned = clean_syllabus("<h4>Grading</h4><script>alert(1)</script>", CANVAS)

    assert "<h4>Grading</h4>" in cleaned
    assert "<script" not in cleaned
    assert "alert" not in cleaned


@pytest.mark.unit
def test_canvas_file_links_become_plain_text_marked_as_files():
    """A file in Canvas keeps its name and file marker but no longer links to Canvas."""
    cleaned = clean_syllabus(
        '<a class="instructure_file_link" '
        'href="https://canvas.example.edu/courses/7/files/9?wrap=1">syllabus.pdf</a>',
        CANVAS,
    )

    assert "syllabus.pdf" in cleaned
    assert 'class="instructure_file_link"' in cleaned
    assert "href" not in cleaned


@pytest.mark.unit
@pytest.mark.parametrize("href", [
    "https://canvas.example.edu/courses/7/modules",
    "/courses/7/pages/office-hours",
])
def test_other_canvas_links_become_plain_text(href):
    """Links to Canvas pages keep their words but no longer lead to Canvas."""
    cleaned = clean_syllabus(f'<a href="{href}">Modules</a>', CANVAS)

    assert "Modules" in cleaned
    assert "href" not in cleaned
    assert "instructure_file_link" not in cleaned


@pytest.mark.unit
def test_outside_links_open_in_a_new_tab():
    """A professor's own website stays a working link that opens separately."""
    cleaned = clean_syllabus('<a href="https://xu-lab.org/">Prof. Xu</a>', CANVAS)

    assert 'href="https://xu-lab.org/"' in cleaned
    assert 'target="_blank"' in cleaned
    assert 'rel="noopener noreferrer"' in cleaned


@pytest.mark.unit
@pytest.mark.parametrize("html", [None, "", "<p>&nbsp;</p>"])
def test_missing_or_blank_syllabus_cleans_to_nothing(html):
    """No syllabus, or one with no visible text, counts as no syllabus."""
    assert clean_syllabus(html, CANVAS) == ""
