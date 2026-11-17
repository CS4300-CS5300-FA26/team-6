"""Making professor-written Canvas syllabus HTML safe to show in Canvas+."""
from html import unescape
from urllib.parse import urlsplit

import nh3
from django.urls import reverse
from django.utils.html import strip_tags

from .files import FILE_PATH

FILE_LINK_CLASS = "instructure_file_link"  # Canvas's own marker on links to course files


def clean_syllabus(html, canvas_url, course_id):
    """Return the syllabus without unsafe markup or links into Canvas, or "" when blank.

    Links to this course's Canvas files point to their Canvas+ viewer instead.
    """
    if not html:
        return ""
    canvas_host = urlsplit(canvas_url).hostname

    def redirect_canvas_links(tag, attribute, value):
        """Keep outside links; send this course's files to Canvas+; drop other Canvas links."""
        if tag != "a" or attribute != "href":
            return value
        try:
            link = urlsplit(value)
        except ValueError:
            return None  # an unreadable link is dropped rather than trusted
        if link.scheme not in ("", "http", "https") or link.hostname not in (None, canvas_host):
            return value
        file_link = FILE_PATH.match(link.path)
        if file_link and int(file_link[1]) == course_id:
            return reverse("course_file", args=[course_id, int(file_link[2])])
        return None

    cleaned = nh3.clean(
        html,
        allowed_classes={"a": {FILE_LINK_CLASS}},
        set_tag_attribute_values={"a": {"target": "_blank"}},
        attribute_filter=redirect_canvas_links,
    )
    return cleaned if unescape(strip_tags(cleaned)).strip() else ""
