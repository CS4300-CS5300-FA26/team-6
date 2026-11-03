"""Making professor-written Canvas syllabus HTML safe to show in Canvas+."""
from html import unescape
from urllib.parse import urlsplit

import nh3
from django.utils.html import strip_tags

FILE_LINK_CLASS = "instructure_file_link"  # Canvas's own marker on links to course files


def clean_syllabus(html, canvas_url):
    """Return the syllabus without unsafe markup or links into Canvas, or "" when blank."""
    if not html:
        return ""
    canvas_host = urlsplit(canvas_url).hostname

    def drop_canvas_links(tag, attribute, value):
        """Keep outside links; remove any link that would lead back into Canvas."""
        if tag != "a" or attribute != "href":
            return value
        try:
            link = urlsplit(value)
        except ValueError:
            return None  # an unreadable link is dropped rather than trusted
        if link.scheme in ("", "http", "https") and link.hostname in (None, canvas_host):
            return None
        return value

    cleaned = nh3.clean(
        html,
        allowed_classes={"a": {FILE_LINK_CLASS}},
        set_tag_attribute_values={"a": {"target": "_blank"}},
        attribute_filter=drop_canvas_links,
    )
    return cleaned if unescape(strip_tags(cleaned)).strip() else ""
