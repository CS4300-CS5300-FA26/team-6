"""Finding the Canvas files a syllabus links to."""
import re
from html.parser import HTMLParser
from urllib.parse import urlsplit

FILE_PATH = re.compile(r"/courses/(\d+)/files/(\d+)")  # matched against a link's path, not HTML


class _LinkCollector(HTMLParser):
    """Collect each link's address and the text inside it."""

    def __init__(self):
        super().__init__()
        self.links = []
        self._open = None

    def handle_starttag(self, tag, attrs):
        """Start recording a link."""
        if tag == "a":
            self._open = (dict(attrs).get("href") or "", [])

    def handle_data(self, data):
        """Keep text that appears inside the current link."""
        if self._open:
            self._open[1].append(data)

    def handle_endtag(self, tag):
        """Finish the current link."""
        if tag == "a" and self._open:
            self.links.append(self._open)
            self._open = None


def linked_files(html, course_id):
    """Return this course's Canvas files linked in the syllabus, once each, in link order."""
    collector = _LinkCollector()
    collector.feed(html or "")
    files, seen = [], set()
    for href, text in collector.links:
        try:
            path = urlsplit(href).path
        except ValueError:
            continue  # a malformed address can't be a Canvas file link
        match = FILE_PATH.match(path)
        name = " ".join("".join(text).split())
        if not match or int(match[1]) != course_id or not name:
            continue
        file_id = int(match[2])
        if file_id not in seen:
            seen.add(file_id)
            files.append({"id": file_id, "name": name})
    return files
