#imports for user login, html templates, availability form, and model.
from django.shortcuts import get_object_or_404, redirect, render
from django.contrib.auth.decorators import login_required
from .forms import AvailabilityForm
from .models import Availability

@login_required
def availability_list(request):
    #display and create availability entries for logged-in student.
    #get only availability records belonging to current user.
    availability_entries = Availability.objects.filter(
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

    #render availability page with form and saved entries
    return render(
        request,
        "availability/availability_list.html",
        {
            "form": form,
            "availability_entries": availability_entries,
        },
    )
@login_required
def availability_edit(request, availability_id):
    #allow change to availability
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
