from django.urls import path

from apps.core.stubs import not_implemented

from . import views

app_name = "reports"

urlpatterns = [
    path("session/<int:sitting_pk>/", views.session_results, name="session"),
    path("session/<int:sitting_pk>/csv/", views.session_csv, name="csv"),
    path("session/<int:sitting_pk>/pdf/", views.session_pdf, name="session_pdf"),
    path("attempt/<int:pk>/", views.attempt_sheet, name="attempt"),
    path("attempt/<int:pk>/void/", not_implemented, name="attempt_void"),  # UX-01, workstream C
    path("attempt/<int:pk>/pdf/", views.attempt_pdf, name="attempt_pdf"),
]
