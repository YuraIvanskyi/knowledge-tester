from django.urls import path

from . import views

app_name = "reports"

urlpatterns = [
    path("session/<int:sitting_pk>/", views.session_results, name="session"),
    path("session/<int:sitting_pk>/csv/", views.session_csv, name="csv"),
    path("session/<int:sitting_pk>/pdf/", views.session_pdf, name="session_pdf"),
    path("attempt/<int:pk>/", views.attempt_sheet, name="attempt"),
    path("attempt/<int:pk>/void/", views.attempt_void, name="attempt_void"),
    path("attempt/<int:pk>/pdf/", views.attempt_pdf, name="attempt_pdf"),
]
