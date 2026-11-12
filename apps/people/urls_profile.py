"""Student profile URLs (workstream D)."""

from django.urls import path

from apps.core.stubs import not_implemented as stub

urlpatterns = [
    path("students/<int:pk>/", stub, name="student"),
    path("students/<int:pk>/notes/", stub, name="student_notes"),
    path("students/<int:pk>/delete/", stub, name="student_delete"),
    path("students/<int:pk>/csv/", stub, name="student_csv"),
    path("students/<int:pk>/pdf/", stub, name="student_pdf"),
]
