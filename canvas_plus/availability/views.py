"""Views for creating and updating student availability."""
#imports for user login, html templates, availability form, and model.
from django.shortcuts import get_object_or_404, redirect, render
from django.contrib.auth.decorators import login_required
from assignments.models import Assignment
from study_plan.exceptions import (
    EmptyAssignmentSelectionError,
    InaccessibleAssignmentError,
    NoEligibleAssignmentsError,
    NoUsableAvailabilityError,
    StudyPlanError,
)
from study_plan.generate import generate_plan
from study_plan.selectors import study_plan_context  # pylint: disable=import-error
from .forms import AvailabilityForm
from .models import Availability

GENERATION_ERRORS = {
    EmptyAssignmentSelectionError: "Select at least one assignment.",
    InaccessibleAssignmentError: "One or more selected assignments are unavailable.",
    NoEligibleAssignmentsError: (
        "No selected assignment has both a due date and a usable effort estimate."
    ),
    NoUsableAvailabilityError: "Add future availability before generating a plan.",
}


@login_required
def availability_list(request):
    """display and create availability entries for logged-in student."""
    #get only availability records belonging to current user.
    availability_entries = Availability.objects.filter( # pylint: disable=no-member
        user=request.user
    ).order_by("date", "start_time")

    #if student submitted form validate and save
    generation_error = None
    if request.method == "POST" and request.POST.get("action") == "generate_plan":
        try:
            generate_plan(
                request.user,
                request.POST.getlist("assignment_ids"),
                allow_late=request.POST.get("allow_late") == "on",
            )
        except StudyPlanError as error:
            generation_error = (
                str(error)
                if isinstance(error, NoEligibleAssignmentsError) and str(error)
                else GENERATION_ERRORS.get(
                    type(error),
                    "The study plan could not be generated. Please try again.",
                )
            )
        else:
            return redirect("availability:list")
        form = AvailabilityForm()
    elif request.method == "POST":
        form = AvailabilityForm(request.POST)
        #only save if validation passes
        if form.is_valid():
            availability = form.save(commit=False)
            #attach logged-in student to new record.
            availability.user = request.user
            #save completed record to database
            availability.save()
            #redirect to page after saving
            return redirect("availability:list")

    else:
        #display empty form when page is first opened
        form = AvailabilityForm()

    #render availability page with form and saved entries
    return render(
        request,
        "availability/availability_list.html",
        {
            "form": form,
            "availability_entries": availability_entries,
            "plan_assignments": Assignment.objects.filter(user=request.user).order_by(
                "due_date", "title"
            ),
            "generation_error": generation_error,
            #study plan section; ?date= picks one day
            **study_plan_context(request.user, request.GET.get("date")),
        },
    )
@login_required
def availability_edit(request, availability_id):
    """allow change to availability"""
    #find requested record, but only if it belonds to logged-in user.
    availability = get_object_or_404(
        Availability,
        id=availability_id,
        user=request.user,
    )
    #if student submitted changes, validate them
    if request.method == "POST":
        form = AvailabilityForm(
            request.POST,
            instance=availability,
        )
        #save updated record if values are valid.
        if form.is_valid():
            form.save()

            #return to availability page.
            return redirect("availability:list")
    else:
        #pre-fill form with existing values
        form = AvailabilityForm(instance=availability)

    #render edit page.
    return render(
        request,
        "availability/availability_edit.html",
        {
            "form": form,
            "availability": availability,
        },
    )
