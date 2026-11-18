"""Calendar feed request views."""

from django.db import DatabaseError
from django.http import HttpResponse, HttpResponseNotFound, HttpResponseServerError
from django.views.decorators.cache import never_cache
from django.views.decorators.debug import sensitive_variables
from django.views.decorators.http import require_safe

from .services import generate_feed, get_subscription_by_token


@never_cache
@require_safe
@sensitive_variables("token", "subscription")
def feed_view(_request, token):
    """Serve the calendar feed addressed by its bearer credential."""
    try:
        subscription = get_subscription_by_token(token)
        if subscription is None or not subscription.user.is_active:
            return HttpResponseNotFound()
        feed_content = generate_feed(subscription.user)
    except DatabaseError:
        return HttpResponseServerError()

    return HttpResponse(feed_content, content_type="text/calendar; charset=utf-8")
