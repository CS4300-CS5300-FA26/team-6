"""Opening the Canvas files a syllabus mentions, right where it mentions them."""
import re
from html import escape, unescape
from html.parser import HTMLParser

from django.template.loader import render_to_string

FILE_PATH = re.compile(r"/courses/(\d+)/files/(\d+)")  # matched against a link's path, not HTML
VIEWER_URL = re.compile(r"/courses/\d+/files/\d+/")  # where the cleaner points this course's files


def _start_tag(tag, attrs):
    """Write a start tag back out, escaping each attribute value."""
    written = "".join(
        f' {name}="{escape(value)}"' if value is not None else f" {name}" for name, value in attrs
    )
    return f"<{tag}{written}>"


class _FileViewerWriter(HTMLParser):
    """Copy cleaned syllabus HTML, swapping file links for a viewer or a download link."""

    def __init__(self):
        super().__init__(convert_charrefs=False)  # keep entities exactly as the cleaner wrote them
        self.out = []
        self._pdf = None  # (viewer address, text parts) while inside a PDF link

    def handle_starttag(self, tag, attrs):
        """Copy a tag, or start replacing a file link."""
        if self._pdf:
            return  # formatting inside a PDF link is folded into its plain name
        found = dict(attrs)
        href = found.get("href") or ""
        if tag == "a" and VIEWER_URL.fullmatch(href):
            if (found.get("title") or "").lower().endswith(".pdf"):
                self._pdf = (href, [])
                return
            attrs = [
                (name, f"{href}?download=1" if name == "href" else value)
                for name, value in attrs if name != "target"  # a download needs no new tab
            ]
        self.out.append(_start_tag(tag, attrs))

    def handle_startendtag(self, tag, attrs):
        """Copy a tag written in self-closing form."""
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag):
        """Copy a closing tag, or finish a PDF link by writing its viewer."""
        if not self._pdf:
            self.out.append(f"</{tag}>")
        elif tag == "a":
            url, text = self._pdf
            self._pdf = None
            name = " ".join(unescape("".join(text)).split())
            viewer = {"url": url, "name": name}
            self.out.append(render_to_string("courses/includes/file_viewer.html", viewer).strip())

    def handle_data(self, data):
        """Copy text, or collect it as a PDF link's name."""
        (self._pdf[1] if self._pdf else self.out).append(data)

    def handle_entityref(self, name):
        """Copy a named entity like &amp; unchanged."""
        self.handle_data(f"&{name};")

    def handle_charref(self, name):
        """Copy a numbered entity like &#39; unchanged."""
        self.handle_data(f"&#{name};")


def embed_file_viewers(html):
    """Open PDF links in place with a viewer, and turn other file links into downloads.

    Expects HTML already run through clean_syllabus, which points file links at Canvas+.
    """
    writer = _FileViewerWriter()
    writer.feed(html)
    writer.close()
    return "".join(writer.out)
