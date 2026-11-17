"""URL routes for calendar subscriptions."""

from django.urls import path

from . import views

urlpatterns = [
    path("<str:token>.ics", views.feed_view, name="calendar_feed"),
]