"""Roster URLs: groups, students, import (workstream B)."""

from django.urls import path

from . import views_roster as views

urlpatterns = [
    path("", views.group_list, name="groups"),
    path("groups/new/", views.group_create, name="group_create"),
    path("groups/<int:pk>/", views.group_detail, name="group"),
    path("groups/<int:pk>/edit/", views.group_edit, name="group_edit"),
    path("groups/<int:pk>/delete/", views.group_delete, name="group_delete"),
    path("groups/<int:pk>/pins/", views.group_pins, name="group_pins"),
    path("students/", views.student_list, name="students"),
    path("students/new/", views.student_create, name="student_create"),
    path("students/<int:pk>/edit/", views.student_edit, name="student_edit"),
    path("import/", views.import_start, name="import"),
    path("import/confirm/", views.import_confirm, name="import_confirm"),
]
