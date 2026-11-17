"""Views for the student's current Canvas courses."""
import requests

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
    get_course_grade,
    get_course_syllabus,
    list_courses,
    list_upcoming_assignments,
    open_course_file,
)
from accounts.course_cache import cached_courses
from accounts.models import CanvasConnection, SavedTokenError
from .current import is_current
from .files import embed_file_viewers
from .grades import current_grade
from .syllabus import clean_syllabus
from .upcoming import due_this_week, group_by_day


@sensitive_variables("token")
def _load_from_canvas(user, load):
    """Load data with the saved connection and one session; return failures as page state."""
    connection = CanvasConnection.objects.filter(user=user).first()
    if connection is None:
        return None, {"canvas_connection_missing": True}
    if not connection.is_valid:
        return None, {"canvas_connection_expired": True}
    try:
        if canvas_origin(connection.canvas_url) != canvas_origin(canvas_base_url()):
            raise SavedTokenError("The configured Canvas host changed.")
        token = connection.get_token()
        with requests.Session() as session:
            return load(connection, token, session), {}
    except (CanvasAuthenticationError, SavedTokenError):
        connection.is_valid = False
        connection.save(update_fields=["is_valid", "updated_at"])
        return None, {"canvas_connection_expired": True}
    except (CanvasAPIError, ImproperlyConfigured):
        return None, {"canvas_unavailable": True}


@sensitive_variables("token")
def _current_courses(connection, token, session):
    """The student's courses whose term hasn't ended."""
    now = timezone.now()
    courses = cached_courses(connection, token, session, list_courses)
    return [course for course in courses if is_current(course, now)]


@sensitive_variables("token")
def _assignments_context(token, courses, session, this_week=False):
    """Group coursework by due day; keep course navigation when it can't load."""
    try:
        assignments = list_upcoming_assignments(token, courses, session=session)
    except CanvasAuthenticationError:
        raise
    except CanvasAPIError:
        return {"assignments_unavailable": True}
    codes = {course["id"]: course.get("course_code") or course["name"] for course in courses}
    for assignment in assignments:
        assignment["course_code"] = codes[assignment["canvas_course_id"]]
    now = timezone.now()
    shown = due_this_week(assignments, now) if this_week else assignments
    return {"assignment_days": group_by_day(shown, now), "assignment_total": len(assignments)}


@login_required
def course_list(request):
    """Show active course tabs and upcoming coursework across all current courses."""
    @sensitive_variables("token")
    def load(connection, token, session):
        courses = _current_courses(connection, token, session)
        return {"courses": courses,
                **_assignments_context(token, courses, session, this_week=True)}

    context, state = _load_from_canvas(request.user, load)
    return render(request, "courses/course_list.html", {**(context or {}), **state})


@sensitive_variables("token")
def _grade_line(token, course_id, session):
    """My current grade line; if only the grade can't load, the rest of the page still shows."""
    try:
        return current_grade(get_course_grade(token, course_id, session=session))
    except CanvasAuthenticationError:
        raise
    except CanvasAPIError:
        return "Unable to load your current grade. Please try again."


@login_required
def course_detail(request, course_id):
    """Show one of the student's current courses with its cleaned syllabus."""

    @sensitive_variables("token")
    def load(connection, token, session):
        # Only courses in the student's own list are requested, so Canvas is never
        # asked about a course that could reject the token and expire the connection.
        course = next((c for c in _current_courses(connection, token, session)
                       if c["id"] == course_id), None)
        if course is None:
            return None
        syllabus = get_course_syllabus(token, course_id, session=session)
        assignments = _assignments_context(token, [course], session)
        return course, syllabus, assignments, _grade_line(token, course_id, session)

    found, state = _load_from_canvas(request.user, load)
    if found is None and not state:
        return render(request, "courses/course_detail.html", {"not_found": True}, status=404)
    context = dict(state)
    if found:
        course, syllabus, assignments_context, context["grade"] = found
        context.update(assignments_context)
        context["course"] = course
        context["syllabus"] = embed_file_viewers(
            clean_syllabus(syllabus, canvas_base_url(), course_id)
        )
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
    def load(connection, token, session):
        # Same rule as the course page: only the student's own current courses are asked about.
        if not any(course["id"] == course_id
                   for course in _current_courses(connection, token, session)):
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
        # A state means a missing or expired connection, or Canvas couldn't provide the file.
        reason, status = ("unavailable", 200) if state else ("not_found", 404)
        if download:  # a download replaces the whole page, so keep the layout and a way back
            context = {"reason": reason, "course_id": course_id}
            return render(request, "courses/file_download_failed.html", context, status=status)
        return _file_message(request, reason, status=status)
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
