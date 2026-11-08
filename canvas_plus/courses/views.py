"""Views for the student's current Canvas courses."""
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ImproperlyConfigured
from django.http import HttpResponse, StreamingHttpResponse
from django.shortcuts import render
from django.utils import timezone
from django.utils.http import content_disposition_header
from django.views.decorators.cache import cache_control
from django.views.decorators.clickjacking import xframe_options_sameorigin
from django.views.decorators.debug import sensitive_variables

from accounts.canvas_client import (
    MAX_FILE_BYTES,
    CanvasAPIError,
    CanvasAuthenticationError,
    CanvasFileTooLarge,
    canvas_base_url,
    canvas_origin,
    download_course_file,
    get_course_file,
    get_course_syllabus,
    list_courses,
    open_course_file,
)
from accounts.models import CanvasConnection, SavedTokenError
from .current import is_current
from .files import linked_files
from .syllabus import clean_syllabus


@sensitive_variables("token")
def _load_from_canvas(user, load):
    """Call load(token) with the student's saved token; on failure, return the state to show."""
    connection = CanvasConnection.objects.filter(user=user).first()
    if connection is None:
        return None, {"canvas_connection_missing": True}
    if not connection.is_valid:
        return None, {"canvas_connection_expired": True}
    try:
        if canvas_origin(connection.canvas_url) != canvas_origin(canvas_base_url()):
            raise SavedTokenError("The configured Canvas host changed.")
        return load(connection.get_token()), {}
    except (CanvasAuthenticationError, SavedTokenError):
        connection.is_valid = False
        connection.save(update_fields=["is_valid", "updated_at"])
        return None, {"canvas_connection_expired": True}
    except (CanvasAPIError, ImproperlyConfigured):
        return None, {"canvas_unavailable": True}


@sensitive_variables("token")
def _current_courses(token):
    """The student's courses whose term hasn't ended."""
    now = timezone.now()
    return [course for course in list_courses(token) if is_current(course, now)]


@login_required
def course_list(request):
    """Show the signed-in student's current Canvas courses."""
    courses, state = _load_from_canvas(request.user, _current_courses)
    return render(request, "courses/course_list.html", {"courses": courses or [], **state})


@login_required
def course_detail(request, course_id):
    """Show one of the student's current courses with its cleaned syllabus."""

    @sensitive_variables("token")
    def load(token):
        # Only courses in the student's own list are requested, so Canvas is never
        # asked about a course that could reject the token and expire the connection.
        course = next((c for c in _current_courses(token) if c["id"] == course_id), None)
        return None if course is None else (course, get_course_syllabus(token, course_id))

    found, state = _load_from_canvas(request.user, load)
    if found is None and not state:
        return render(request, "courses/course_detail.html", {"not_found": True}, status=404)
    context = dict(state)
    if found:
        course, syllabus = found
        context["course"] = course
        context["syllabus"] = clean_syllabus(syllabus, canvas_base_url())
        context["files"] = linked_files(syllabus, course_id)  # read before cleaning drops the links
    return render(request, "courses/course_detail.html", context)


def _stream(response):
    """Pass a Canvas file through in pieces, closing the connection when done."""
    try:
        yield from response.iter_content(chunk_size=64 * 1024)
    finally:
        response.close()


def _file_message(request, reason, status=200):
    """A short message shown inside the file viewer instead of the file."""
    return render(request, "courses/file_message.html", {"reason": reason}, status=status)


@login_required
@xframe_options_sameorigin
@cache_control(private=True)
def course_file(request, course_id, file_id):
    """Show one syllabus file inside Canvas+: a PDF preview, or a download."""
    download = request.GET.get("download") == "1"

    @sensitive_variables("token")
    def load(token):
        # Same rule as the course page: only the student's own current courses are asked about.
        if not any(course["id"] == course_id for course in _current_courses(token)):
            return None
        info = get_course_file(token, course_id, file_id)
        if download:
            return info, open_course_file(token, info["url"])  # streamed, so any size
        if info["size"] > MAX_FILE_BYTES:
            return info, None  # too large to preview: nothing is fetched
        try:
            return info, download_course_file(token, info["url"])
        except CanvasFileTooLarge:
            return info, None

    found, state = _load_from_canvas(request.user, load)
    if found is None:
        if state:  # missing or expired connection, or Canvas couldn't provide the file
            return _file_message(request, "unavailable")
        return _file_message(request, "not_found", status=404)
    info, body = found
    if download:
        response = StreamingHttpResponse(_stream(body), content_type="application/octet-stream")
        response["Content-Disposition"] = content_disposition_header(True, info["name"])
        return response
    if body is None:
        return _file_message(request, "too_large")
    if not body.startswith(b"%PDF-"):
        return _file_message(request, "not_pdf")  # checked from the bytes, not the file's label
    response = HttpResponse(body, content_type="application/pdf")
    response["Content-Disposition"] = content_disposition_header(False, info["name"])
    return response
