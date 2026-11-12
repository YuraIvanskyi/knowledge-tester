"""Roster URLs: groups, students, import (workstream B)."""

from django.urls import path

from apps.core.stubs import not_implemented as stub

urlpatterns = [
    path("", stub, name="groups"),
    path("groups/new/", stub, name="group_create"),
    path("groups/<int:pk>/", stub, name="group"),
    path("groups/<int:pk>/edit/", stub, name="group_edit"),
    path("groups/<int:pk>/delete/", stub, name="group_delete"),
    path("groups/<int:pk>/pins/", stub, name="group_pins"),
    path("students/", stub, name="students"),
    path("students/new/", stub, name="student_create"),
    path("students/<int:pk>/edit/", stub, name="student_edit"),
    path("import/", stub, name="import"),
    path("import/confirm/", stub, name="import_confirm"),
]
