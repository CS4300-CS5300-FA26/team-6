"""Views for account creation, sign in, and sign out."""
from django.contrib.auth import login, logout
from django.utils.http import url_has_allowed_host_and_scheme
from django.contrib.auth.forms import AuthenticationForm
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST
from django.contrib.auth.decorators import login_required

from .forms import RegistrationForm
from .forms import CanvasConnectionForm


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
    next_url = request.POST.get("next") or request.GET.get("next")

    if request.method == "POST" and form.is_valid():
        login(request, form.get_user())
        next_url = request.POST.get("next") or request.GET.get("next")
        if next_url and url_has_allowed_host_and_scheme(
            next_url,
            allowed_hosts={request.get_host()},
            require_https=request.is_secure(),
            ):
            return redirect(next_url)
        return redirect("home")

    return render(
        request,
        "accounts/login.html",
        {"form": form, "next": next_url},
    )

@login_required
def connect_canvas(request):
    """Show the Canvas API token form"""
    form = CanvasConnectionForm(request.POST or None)

    if request.method == "POST" and form.is_valid():

        token = form.cleaned_data["token"]

        # TODO: validate the canvas API token through the canvas API client

    return render(request, "accounts/connect_canvas.html", {"form": form})




@require_POST
def logout_view(request):
    """End the session; POST only so the CSRF token protects it."""
    logout(request)
    return redirect("home")
