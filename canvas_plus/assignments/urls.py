"""URL routes"""
from django.urls import path
from . import views

urlpatterns = [
    path("generate/", views.generate_study_plan, name="generate_plan"),
    path(
        "attachments/<int:attachment_id>/remove/",
        views.remove_attachment,
        name="remove_attachment",
    ),
    path("attachments/<int:attachment_id>/", views.open_attachment, name="open_attachment"),
    path(
        "<int:course_id>/<int:assignment_id>/attachments/",
        views.upload_attachments,
        name="upload_attachments",
    ),
    path("", views.assignment_list, name="assignment_list"),
    path(
        "<int:course_id>/<int:assignment_id>/effort/",
        views.edit_effort_estimate,
        name="edit_effort_estimate",
    ),
]
