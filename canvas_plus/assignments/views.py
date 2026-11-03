"""Django views"""
import requests
from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.core.exceptions import ImproperlyConfigured
from django.shortcuts import render, get_object_or_404, redirect
from django.utils import timezone
from django.views.decorators.debug import sensitive_variables
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
from .forms import EffortEstimateForm
from .models import Assignment

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


@login_required
@sensitive_variables("token")
def assignment_list(request):
    """Show the signed-in student's current upcoming Canvas assignments."""
    assignments = []
    unavailable_message = ""
    connection_expired = False
    connection_missing = False
    connection = CanvasConnection.objects.filter(user=request.user).first()
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
                # Create or update the local database record that mirrors
                # this Canvas assignment for the signed-in student.
                local_assignment, _created = Assignment.objects.update_or_create(
                    user=request.user,
                    canvas_assignment_id=assignment["id"],
                    defaults={
                        "canvas_course_id": assignment["course_id"],
                        "title": assignment["title"],
                        "course": assignment["course_name"],
                        "due_date": assignment["due_date"],
                    },
                )

                # Expose the local database ID to the template so local
                # features such as effort estimation can link to this row.
                assignment["local_assignment_id"] = local_assignment.id

                # Expose the currently saved effort estimate, if one exists.
                assignment["estimated_effort_minutes"] = (
                    local_assignment.estimated_effort_minutes
                )

                # Expose whether the estimate was automatic or manually overridden.
                assignment["effort_estimate_source"] = (
                    local_assignment.effort_estimate_source
                )
        except (CanvasAuthenticationError, SavedTokenError):
            connection.is_valid = False
            connection.save(update_fields=["is_valid", "updated_at"])
            connection_expired = True
        except (CanvasAPIError, ImproperlyConfigured):
            unavailable_message = "Unable to load upcoming assignments. Please try again."

    context = {
        "assignments": assignments,
        "canvas_connection_expired": connection_expired,
        "canvas_connection_missing": connection_missing,
        "assignments_unavailable": (
            bool(unavailable_message) or connection_expired or connection_missing
        ),
        "assignments_unavailable_message": unavailable_message,
        **graded_context,
    }
    return render(request, "assignments/assignment_list.html", context)

@login_required
def edit_effort_estimate(request, assignment_id):
    """Allow a student to manually update their own assignment effort estimate."""

    # Retrieve the requested assignment only if it belong to the currently logged-in student.
    # Including user=request.user prevents one student from editing another student's assignment by changing the URL.
    assignment = get_object_or_404(
        Assignment,
        id=assignment_id,
        user=request.user,
    )

    # Handle a submitted manual estimate.
    if request.method == "POST":
        # Bind the submitted value to the existing Assignment record.
        form = EffortEstimateForm(
            request.POST,
            instance=assignment,
        )

        # Only save if the form passes validation.
        if form.is_valid():
            # Do not save immediately because we also need to mark the estimate as manually entered.
            updated_assignment = form.save(commit=False)

            # Record that the student manually changed the estimate.
            updated_assignment.effort_estimate_source = "manual"

            # Save the updated estimate and source.
            updated_assignment.save(
                update_fields=[
                    "estimated_effort_minutes",
                    "effort_estimate_source",
                ]
            )

            # Return the student to the assignment page/list.
            return redirect("assignment_list")

    else:
        # Pre-fill the form with the current effort estimate.
        form = EffortEstimateForm(instance=assignment)

    # Show the edit form initially or redisplay it with validation errors after an invalid POST.
    return render(
        request,
        "assignments/edit_effort_estimate.html",
        {
            "form": form,
            "assignment": assignment,
        },
    )
