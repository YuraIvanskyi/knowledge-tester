"""Group gradebook URLs (workstream E)."""

from django.urls import path

from apps.core.stubs import not_implemented as stub

urlpatterns = [
    path("groups/<int:pk>/gradebook/", stub, name="gradebook"),
    path("groups/<int:pk>/gradebook/csv/", stub, name="gradebook_csv"),
]
