"""Site-wide views."""
from django.shortcuts import redirect, render

LOGGED_IN_HOME = "assignment_list"  # where logged-in users start; change for the dashboard


def landing(request):
    """Logged-out visitors see the landing page; logged-in users go to their home page."""
    if request.user.is_authenticated:
        return redirect(LOGGED_IN_HOME)
    return render(request, "landing.html")
