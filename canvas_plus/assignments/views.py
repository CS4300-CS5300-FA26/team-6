"""Django views"""
import requests
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.http import Http404
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.debug import sensitive_variables
from django.views.decorators.http import require_POST
from accounts.canvas_client import (
    CanvasAPIError,
    CanvasAuthenticationError,
    canvas_base_url,
    canvas_origin,
    list_courses,
    list_graded_submissions,
    list_upcoming_assignments,
)
from accounts.models import CanvasConnection, SavedTokenError
from .grades import RECENT_WINDOW, recent_grades
from .priority import priority
from .uploads import save_attachments, validate_batch

# Enrollments rarely change mid-term; reconnecting Canvas starts a fresh cache key.
COURSE_CACHE_SECONDS = 60 * 60


@sensitive_variables("token")
def recently_graded_context(token, courses, session):
    """Context for the Recently graded section."""
    try:
        submissions = list_graded_submissions(
            token, courses, timezone.now() - RECENT_WINDOW, session=session
        )
    except CanvasAuthenticationError:
        raise
    except CanvasAPIError:
        return {"recently_graded_error": "Unable to load recently graded work right now."}
    else:
        return {"show_recently_graded": True, "recently_graded": recent_grades(submissions)}


@sensitive_variables("token")
def load_canvas_context(user):
    """Check the connection and load Canvas data for the student."""
    assignments = []
    unavailable_message = ""
    connection_expired = False
    connection_missing = False
    connection = CanvasConnection.objects.filter(user=user).first()
    graded_context = {}

    if connection is None:
        connection_missing = True
    elif not connection.is_valid:
        connection_expired = True
    else:
        try:
            try:
                origins_match = canvas_origin(connection.canvas_url) == canvas_origin(
                    canvas_base_url()
                )
            except ValueError:
                origins_match = False
            if not origins_match:
                raise SavedTokenError("The configured Canvas host changed.")

            token = connection.get_token()
            with requests.Session() as session:
                courses_key = f"canvas-courses:{connection.pk}:{connection.updated_at.timestamp()}"
                courses = cache.get(courses_key)
                if courses is None:
                    courses = list_courses(token, session=session)
                    cache.set(courses_key, courses, COURSE_CACHE_SECONDS)
                assignments = list_upcoming_assignments(token, courses, session=session)
                graded_context = recently_graded_context(token, courses, session)
            now = timezone.now()
            for assignment in assignments:
                assignment["priority"] = priority(
                    assignment["due_date"], assignment["submitted"], now
                )
        except (CanvasAuthenticationError, SavedTokenError):
            connection.is_valid = False
            connection.save(update_fields=["is_valid", "updated_at"])
            connection_expired = True
        except (CanvasAPIError, ImproperlyConfigured):
            unavailable_message = "Unable to load upcoming assignments. Please try again."

    return {
        "assignments": assignments,
        "canvas_connection_expired": connection_expired,
        "canvas_connection_missing": connection_missing,
        "assignments_unavailable": (
            bool(unavailable_message) or connection_expired or connection_missing
        ),
        "assignments_unavailable_message": unavailable_message,
        **graded_context,
    }


@login_required
def assignment_list(request):
    """Show the signed-in student's current upcoming Canvas assignments."""
    context = load_canvas_context(request.user)
    return render(request, "assignments/assignment_list.html", context)


@login_required
@require_POST
def upload_attachments(request, course_id, assignment_id):
    """Attach a validated file batch to the student's live Canvas assignment."""
    files = request.FILES.getlist("files")
    try:
        validate_batch(files)
    except ValidationError as error:
        messages.error(request, error.messages[0])
        return redirect("assignment_list")

    context = load_canvas_context(request.user)
    if context["assignments_unavailable"]:
        messages.error(request, "Unable to load Canvas assignments. Please reconnect or try again.")
        return redirect("assignment_list")

    assignment = next((
        item for item in context["assignments"]
        if item["canvas_assignment_id"] == assignment_id
        and item["canvas_course_id"] == course_id
    ), None)
    if assignment is None:
        raise Http404("Assignment not found")

    try:
        save_attachments(request.user, assignment, files)
    # Production S3 storage raises botocore errors beyond OSError.
    except Exception:  # pylint: disable=broad-exception-caught
        messages.error(request, "Unable to upload files. Please try again.")
    else:
        messages.success(request, "Files attached successfully.")
    return redirect("assignment_list")
