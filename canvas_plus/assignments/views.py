"""Django views"""
from django.shortcuts import render
from .models import Assignment


def assignment_list(request):
    """ View for listing assignments. """
    assignments = Assignment.objects.all().order_by("due_date") # pylint: disable=no-member
    return render(request, "assignments/assignment_list.html", {"assignments": assignments})
