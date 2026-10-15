"""Views for account creation, sign in, and sign out."""
from django.contrib.auth import login, logout
from django.contrib.auth.forms import AuthenticationForm
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from .forms import RegistrationForm


def register_view(request):
    """Show the registration form, or create the account on a valid POST."""
    form = RegistrationForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        form.save()
        return redirect("login")
    return render(request, "accounts/register.html", {"form": form})


def login_view(request):
    """Show the sign-in form, or start a session on valid credentials."""
    form = AuthenticationForm(request, data=request.POST or None)
    if request.method == "POST" and form.is_valid():
        login(request, form.get_user())
        return redirect("home")
    return render(request, "accounts/login.html", {"form": form})


@require_POST
def logout_view(request):
    """End the session; POST only so the CSRF token protects it."""
    logout(request)
    return redirect("login")
