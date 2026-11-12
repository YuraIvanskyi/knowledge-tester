"""Student profile URLs (workstream D)."""

from django.urls import path

from . import views_profile as views

urlpatterns = [
    path("students/<int:pk>/", views.student_profile, name="student"),
    path("students/<int:pk>/notes/", views.student_notes, name="student_notes"),
    path("students/<int:pk>/delete/", views.student_delete, name="student_delete"),
    path("students/<int:pk>/csv/", views.student_csv, name="student_csv"),
    path("students/<int:pk>/pdf/", views.student_pdf, name="student_pdf"),
]
