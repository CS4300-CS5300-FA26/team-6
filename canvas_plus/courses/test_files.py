"""Unit tests for turning a cleaned syllabus's file links into viewers and downloads."""
import pytest

from courses.files import embed_file_viewers  # pylint: disable=import-error


def file_link(title, file_id, text):
    """A file link as the cleaner leaves it: pointing at Canvas+, opening in a new tab."""
    return (
        f'<a class="instructure_file_link" title="{title}" href="/courses/7/files/{file_id}/" '
        f'target="_blank" rel="noopener noreferrer">{text}</a>'
    )


@pytest.mark.unit
def test_pdf_link_becomes_a_viewer_in_place():
    """A PDF opens right where the syllabus mentions it, with a download link too."""
    html = embed_file_viewers(f"<p>Syllabus: {file_link('syllabus.pdf', 9, 'syllabus.pdf')}</p>")

    assert html.startswith("<p>Syllabus: <details")
    assert "<summary>syllabus.pdf</summary>" in html
    assert '<iframe src="/courses/7/files/9/"' in html
    assert 'href="/courses/7/files/9/?download=1"' in html


@pytest.mark.unit
def test_other_file_link_becomes_a_download_link():
    """A file that can't be previewed is just a link that downloads it."""
    html = embed_file_viewers(file_link("Lecture 0--Overview.pptx", 10, "Lecture 0"))

    assert 'href="/courses/7/files/10/?download=1"' in html
    assert ">Lecture 0</a>" in html
    assert "<details" not in html


@pytest.mark.unit
def test_rest_of_the_syllabus_is_unchanged():
    """Headings, entities, line breaks, and outside links pass through exactly."""
    html = (
        "<h4>Grading &amp; Policies</h4><p>Line<br>two</p>"
        '<a href="https://xu-lab.org/" target="_blank" rel="noopener noreferrer">Prof. Xu</a>'
    )

    assert embed_file_viewers(html) == html
