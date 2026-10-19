"""Django views"""
from django.shortcuts import render
from accounts.connections import connection_status  # pylint: disable=import-error
from .models import Assignment


def assignment_list(request):
    """ View for listing assignments. """
    assignments = Assignment.objects.all().order_by("due_date") # pylint: disable=no-member
    context = {"assignments": assignments, **connection_status(request.user)}
    return render(request, "assignments/assignment_list.html", context)
