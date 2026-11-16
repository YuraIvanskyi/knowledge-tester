from django.urls import path

from . import views

app_name = "core"

urlpatterns = [
    path("", views.landing, name="landing"),
    path("teach/", views.dashboard, name="dashboard"),
    path("teach/help/", views.help_page, name="help"),
    path("healthz", views.healthz, name="healthz"),
]
