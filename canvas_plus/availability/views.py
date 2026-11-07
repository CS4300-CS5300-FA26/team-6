"""Views for creating and updating student availability."""
from datetime import date, datetime, time, timedelta

#imports for user login, html templates, availability form, and model.
from django.db.models import Q
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
    all_planning_assignments = Assignment.objects.filter(
        user=request.user,
        sync_state="synced",
    )
    planning_assignments = all_planning_assignments

    query = request.GET.get("q", "").strip()
    course = request.GET.get("course", "").strip()
    due_from = request.GET.get("due_from")
    due_to = request.GET.get("due_to")
    no_due_date = request.GET.get("no_due_date") == "1"
    assignment_filter_error = ""

    if query:
        planning_assignments = planning_assignments.filter(
            Q(title__icontains=query) | Q(course__icontains=query)
        )
    if course:
        planning_assignments = planning_assignments.filter(course=course)

    date_filter_submitted = due_from is not None or due_to is not None
    if no_due_date:
        planning_assignments = planning_assignments.filter(due_date__isnull=True)
    elif not date_filter_submitted:
        planning_assignments = planning_assignments.filter(
            due_date__gte=window_start,
            due_date__lt=window_end,
        )
    else:
        try:
            start_day = date.fromisoformat(due_from) if due_from else None
            end_day = date.fromisoformat(due_to) if due_to else None
        except ValueError:
            assignment_filter_error = "Enter valid start and end dates."
            planning_assignments = planning_assignments.none()
        else:
            if start_day is not None:
                start_bound = timezone.make_aware(
                    datetime.combine(start_day, time.min),
                    local_timezone,
                )
                planning_assignments = planning_assignments.filter(
                    due_date__gte=start_bound,
                )
            if end_day is not None:
                end_bound = timezone.make_aware(
                    datetime.combine(end_day + timedelta(days=1), time.min),
                    local_timezone,
                )
                planning_assignments = planning_assignments.filter(
                    due_date__lt=end_bound,
                )

    planning_assignments = planning_assignments.order_by("due_date", "title", "pk")
    planning_courses = all_planning_assignments.values_list(
        "course", flat=True
    ).distinct().order_by("course")

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
            "planning_courses": planning_courses,
            "assignment_query": query,
            "assignment_course_filter": course,
            "assignment_due_from": due_from or "",
            "assignment_due_to": due_to or "",
            "assignment_no_due_date": no_due_date,
            "assignment_filter_error": assignment_filter_error,
            "assignment_filters_active": bool(
                query or course or date_filter_submitted or no_due_date
            ),
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
