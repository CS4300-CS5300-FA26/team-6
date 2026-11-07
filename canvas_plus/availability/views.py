"""Views for creating and updating student availability."""
from datetime import datetime, time, timedelta

#imports for user login, html templates, availability form, and model.
from django.shortcuts import get_object_or_404, redirect, render
from django.contrib.auth.decorators import login_required
from django.utils import timezone
from assignments.models import Assignment
from assignments.views import load_canvas_context
from study_plan.selectors import study_plan_context  # pylint: disable=import-error
from .forms import AvailabilityForm
from .models import Availability

@login_required
def availability_list(request):
    """display and create availability entries for logged-in student."""
    #get only availability records belonging to current user.
    availability_entries = Availability.objects.filter( # pylint: disable=no-member
        user=request.user
    ).order_by("date", "start_time")

    #if student submitted form validate and save
    if request.method =="POST":
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

    canvas_context = load_canvas_context(request.user, sync_all_assignments=True)
    planning_assignments_unavailable = bool(
        canvas_context["assignments_unavailable"]
        or canvas_context.get("assignment_sync_error")
    )
    local_today = timezone.localdate()
    local_timezone = timezone.get_current_timezone()
    window_start = timezone.make_aware(
        datetime.combine(local_today, time.min),
        local_timezone,
    )
    window_end = timezone.make_aware(
        datetime.combine(local_today + timedelta(days=14), time.min),
        local_timezone,
    )
    planning_assignments = Assignment.objects.filter(
        user=request.user,
        sync_state="synced",
        due_date__gte=window_start,
        due_date__lt=window_end,
    ).order_by("due_date", "title", "pk")

    #render availability page with form and saved entries
    return render(
        request,
        "availability/availability_list.html",
        {
            "form": form,
            "availability_entries": availability_entries,
            **canvas_context,
            "planning_assignments": planning_assignments,
            "planning_assignments_unavailable": planning_assignments_unavailable,
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
