"""URL routes"""
from django.urls import path
from . import views

urlpatterns = [
    path("", views.assignment_list, name="assignment_list"),
    path("<int:assignment_id>/effort/",views.edit_effort_estimate,name="edit_effort_estimate",),
]
