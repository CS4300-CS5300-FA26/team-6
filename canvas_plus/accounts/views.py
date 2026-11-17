"""Views for account creation, sign in, and sign out."""
from django.contrib.auth import login, logout
from django.utils.http import url_has_allowed_host_and_scheme
from django.contrib.auth.forms import AuthenticationForm
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ImproperlyConfigured
from django.views.decorators.cache import never_cache
from django.views.decorators.debug import sensitive_post_parameters, sensitive_variables

from calendar_feed.models import CalendarSubscription
from calendar_feed.services import issue_subscription

from .forms import CanvasConnectionForm, RegistrationForm
from .canvas_client import CanvasAPIError, CanvasAuthenticationError, canvas_base_url, list_courses
from .models import CanvasConnection


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

@sensitive_post_parameters("token")
@sensitive_variables("token", "feed_url")
@never_cache
@login_required
def settings_view(request):
    """Manage account settings, including the user's Canvas connection."""
    calendar_action = (
        request.method == "POST" and request.POST.get("action") == "calendar"
    )
    feed_url = None
    if calendar_action:
        token = issue_subscription(request.user)
        feed_url = request.build_absolute_uri(
            reverse("calendar_feed", args=[token])
        )

    form = CanvasConnectionForm(
        request.POST if request.method == "POST" and not calendar_action else None
    )
    connection = CanvasConnection.objects.filter(user=request.user).first()
    courses = None

    if request.method == "POST" and not calendar_action and form.is_valid():

        token = form.cleaned_data["token"]

        try:
            courses = list_courses(token)
            candidate = connection or CanvasConnection(user=request.user)
            candidate.set_token(token)
            candidate.canvas_url = canvas_base_url()
            candidate.save()
            connection = candidate
        except CanvasAuthenticationError:
            courses = None
            form.add_error("token", "Invalid token. Check your token and try again.")
        except CanvasAPIError as error:
            courses = None
            form.add_error(None, str(error))
        except ImproperlyConfigured:
            courses = None
            form.add_error(
                None, "Canvas connection is not configured. Please contact the administrator."
            )

    return render(request, "accounts/settings.html", {
        "form": form,
        "courses": courses,
        "canvas_connected": courses is not None,
        "saved_token_last_four": connection.token_last_four if connection else "",
        "canvas_connection_expired": connection is not None and not connection.is_valid,
        "calendar_feed_url": feed_url,
        "has_calendar_subscription": CalendarSubscription.objects.filter(
            user=request.user
        ).exists(),
    })


@require_POST
def logout_view(request):
    """End the session; POST only so the CSRF token protects it."""
    logout(request)
    return redirect("home")
