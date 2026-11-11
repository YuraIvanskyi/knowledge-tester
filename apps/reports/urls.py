from django.urls import path

from . import views

app_name = "reports"

urlpatterns = [
    path("session/<int:sitting_pk>/", views.session_results, name="session"),
    path("session/<int:sitting_pk>/csv/", views.session_csv, name="csv"),
    path("attempt/<int:pk>/", views.attempt_sheet, name="attempt"),
]
