"""Unit tests for finding the Canvas files a syllabus links to."""
import pytest

from courses.files import linked_files  # pylint: disable=import-error


@pytest.mark.unit
def test_finds_this_courses_files_in_link_order():
    """Full and relative Canvas file links both count, named by their link text."""
    html = (
        '<a href="https://canvas.example.edu/courses/7/files/9?wrap=1"><span>Syllabus</span></a>'
        '<a href="/courses/7/files/10/download">Lecture 1</a>'
    )

    assert linked_files(html, 7) == [
        {"id": 9, "name": "Syllabus"},
        {"id": 10, "name": "Lecture 1"},
    ]


@pytest.mark.unit
def test_ignores_links_that_are_not_this_courses_files():
    """Other courses' files, Canvas pages, outside sites, and nameless links are left out."""
    html = (
        '<a href="/courses/8/files/9">Old course file</a>'
        '<a href="/courses/7/modules">Modules</a>'
        '<a href="https://xu-lab.org/">Prof. Xu</a>'
        '<a href="/courses/7/files/11"></a>'
    )

    assert not linked_files(html, 7)


@pytest.mark.unit
def test_a_file_linked_twice_is_listed_once():
    """The same file linked in two places shows up once."""
    html = '<a href="/courses/7/files/9">Syllabus</a> ... <a href="/courses/7/files/9">here</a>'

    assert linked_files(html, 7) == [{"id": 9, "name": "Syllabus"}]


@pytest.mark.unit
@pytest.mark.parametrize("html", [None, ""])
def test_no_syllabus_has_no_files(html):
    """A course without a syllabus links to no files."""
    assert not linked_files(html, 7)
