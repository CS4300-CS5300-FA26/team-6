#URL routes for the availability application.

# Import Django's URL path helper and availability views
from django.urls import path
from . import views

#give app namespace so there are no url conflicts
app_name = "availability"

urlpatterns = [
    #Main page for viewing and creating availability entries.
    path(
        "",
        views.availability_list,
        name="list",
    ),
    #page for editing existing availability
    path(
        "<int:availability_id>/edit/",
        views.availability_edit,
        name="edit",
    ),
]
