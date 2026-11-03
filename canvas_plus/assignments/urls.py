"""URL routes"""
from django.urls import path
from . import views

urlpatterns = [
    path(
        "<int:course_id>/<int:assignment_id>/attachments/",
        views.upload_attachments,
        name="upload_attachments",
    ),
    path("", views.assignment_list, name="assignment_list"),
]
