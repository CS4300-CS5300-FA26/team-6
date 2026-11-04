"""Django views"""
import logging

import requests
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.debug import sensitive_variables
from django.views.decorators.http import require_GET, require_http_methods, require_POST
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
from .models import Attachment, Assignment
from .priority import priority
from .uploads import save_attachments, validate_batch
from .forms import EffortEstimateForm 
from study_plan.effort_estimation import estimate_and_save_assignment_effort

# Enrollments rarely change mid-term; reconnecting Canvas starts a fresh cache key.
COURSE_CACHE_SECONDS = 60 * 60
logger = logging.getLogger(__name__)


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
                assignment["due_date"],
                assignment["submitted"],
                now,
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
    if not context["assignments_unavailable"]:
        assignments_by_id = {
            item["canvas_assignment_id"]: item for item in context["assignments"]
        }
        for assignment in assignments_by_id.values():
            assignment["attachments"] = []
            assignment["estimated_effort_minutes"] = None
            assignment["effort_estimate_source"] = None
        
        # Load existing local Assignment rows only.
        # This does not create database records just from viewing the page.
        local_assignments = Assignment.objects.filter(
            user=request.user,
            canvas_assignment_id__in=assignments_by_id,
        )

        # Merge saved effort-estimate information into the Canvas dictionaries.
        for local_assignment in local_assignments:
            canvas_assignment = assignments_by_id.get(
                local_assignment.canvas_assignment_id
            )

            if canvas_assignment is not None:
                canvas_assignment["estimated_effort_minutes"] = (
                    local_assignment.estimated_effort_minutes
                )
                canvas_assignment["effort_estimate_source"] = (
                    local_assignment.effort_estimate_source
                )
        # Django supplies model managers dynamically.
        attachments = Attachment.objects.filter(  # pylint: disable=no-member
            user=request.user,
            assignment__canvas_assignment_id__in=assignments_by_id,
        ).select_related("study_file", "assignment").order_by("study_file__uploaded_at")
        for attachment in attachments:
            assignments_by_id[attachment.assignment.canvas_assignment_id]["attachments"].append(
                attachment
            )
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


@login_required
@require_GET
def open_attachment(request, attachment_id):
    """Download an owned attachment without exposing a public storage URL."""
    attachment = get_object_or_404(Attachment, pk=attachment_id, user=request.user)
    study_file = attachment.study_file
    try:
        # S3 opens lazily, so check for a missing object before starting a response.
        if not study_file.file.storage.exists(study_file.file.name):
            raise FileNotFoundError("Stored attachment is missing")
        stored_file = study_file.file.open("rb")
        try:
            # FileResponse seeks to set Content-Length, which is when S3 fetches the object.
            # ponytail: The dyno streams the bytes (max 25 MiB); signed URLs are the upgrade.
            return FileResponse(
                stored_file, as_attachment=True, filename=study_file.original_name,
            )
        except Exception:
            stored_file.close()
            raise
    # Storage backends raise provider-specific exceptions beyond OSError.
    except Exception:  # pylint: disable=broad-exception-caught
        logger.exception("Unable to open attachment %s", attachment_id)
        messages.error(request, "Unable to open file. Please try again.")
        return redirect("assignment_list")


@login_required
@require_http_methods(["GET", "POST"])
def remove_attachment(request, attachment_id):
    """Confirm removal, then unlink only the student's chosen attachment."""
    attachment = get_object_or_404(Attachment, pk=attachment_id, user=request.user)
    if request.method == "POST":
        attachment.delete()
        messages.success(request, "File removed.")
        return redirect("assignment_list")
    return render(request, "assignments/remove_attachment.html", {"attachment": attachment})
    
@login_required
def edit_effort_estimate(request, course_id, assignment_id):
    """Allow a student to set or update an assignment effort estimate."""

    # First look for an existing local Assignment owned by this student.
    # If one exists, we can edit it without requiring another Canvas request.
    local_assignment = Assignment.objects.filter(
        user=request.user,
        canvas_course_id=course_id,
        canvas_assignment_id=assignment_id,
    ).first()

    # If the student does not already have a local Assignment row,
    # verify the requested assignment against their live Canvas data.
    if local_assignment is None:
        context = load_canvas_context(request.user)

        # Do not create a new local row when Canvas data cannot be loaded.
        if context["assignments_unavailable"]:
            messages.error(
                request,
                "Unable to load Canvas assignments. Please reconnect or try again.",
            )
            return redirect("assignment_list")

        # Find the requested Canvas assignment using both stable identifiers.
        canvas_assignment = next(
            (
                item
                for item in context["assignments"]
                if item["canvas_assignment_id"] == assignment_id
                and item["canvas_course_id"] == course_id
            ),
            None,
        )

        # Reject an assignment that is not present in this student's Canvas data.
        if canvas_assignment is None:
            raise Http404("Assignment not found")

    else:
        # Build the display information from the existing local Assignment.
        # This avoids requiring Canvas just to edit an already saved estimate.
        canvas_assignment = {
            "title": local_assignment.title,
            "course_name": local_assignment.course,
            "due_date": local_assignment.due_date,
            "canvas_course_id": local_assignment.canvas_course_id,
            "canvas_assignment_id": local_assignment.canvas_assignment_id,
            "estimated_effort_minutes": local_assignment.estimated_effort_minutes,
            "effort_estimate_source": local_assignment.effort_estimate_source,
        }

    # Handle a submitted manual estimate.
    if request.method == "POST":

        # If no local row exists yet, create an unsaved Assignment
        # from the verified Canvas snapshot.
        if local_assignment is None:
            local_assignment = Assignment(
                user=request.user,
                canvas_course_id=course_id,
                canvas_assignment_id=assignment_id,
                title=canvas_assignment["title"],
                course=canvas_assignment["course_name"],
                due_date=canvas_assignment["due_date"],
            )

        # Bind the submitted estimate to the local Assignment.
        form = EffortEstimateForm(
            request.POST,
            instance=local_assignment,
        )

        # Save a valid student-entered estimate.
        if form.is_valid():
            updated_assignment = form.save(commit=False)

            # Record that the student manually entered or changed the value.
            updated_assignment.effort_estimate_source = "manual"

            # Save the new local row or update the existing one.
            updated_assignment.save()

            return redirect("assignment_list")

    else:
        # If this Canvas assignment does not already exist locally, create it when the student explicitly opens the effort page.
        if local_assignment is None:
            local_assignment = Assignment.objects.create(
                user=request.user,
                canvas_course_id=course_id,
                canvas_assignment_id=assignment_id,
                title=canvas_assignment["title"],
                course=canvas_assignment["course_name"],
                due_date=canvas_assignment["due_date"],
            )

            # Attempt to generate an automatic effort estimate using the assignment description supplied by Canvas.
            # If there is not enough information, the helper returns None and the student can enter an estimate manually instead.
            estimate_and_save_assignment_effort(
                assignment=local_assignment,
                assignment_information=canvas_assignment.get("description"),
            )

            # Add any newly generated estimate to the template context.
            canvas_assignment["estimated_effort_minutes"] = (
                local_assignment.estimated_effort_minutes
            )
            canvas_assignment["effort_estimate_source"] = (
                local_assignment.effort_estimate_source
            )

        # Pre-fill the form with either the saved automatic estimate or an existing manual estimate.
        form = EffortEstimateForm(instance=local_assignment)

    # Display the manual effort-estimate form.
    return render(
        request,
        "assignments/edit_effort_estimate.html",
        {
            "form": form,
            "assignment": canvas_assignment,
        },
    )
