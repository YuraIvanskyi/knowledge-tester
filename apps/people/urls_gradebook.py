"""Group gradebook URLs (workstream E)."""

from django.urls import path

from . import views_gradebook

urlpatterns = [
    path("groups/<int:pk>/gradebook/", views_gradebook.gradebook, name="gradebook"),
    path("groups/<int:pk>/gradebook/csv/", views_gradebook.gradebook_csv, name="gradebook_csv"),
]
