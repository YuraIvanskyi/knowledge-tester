"""Admin area URLs (prefix /manage/, workstream A)."""

from django.urls import path

from apps.core.stubs import not_implemented as stub

app_name = "manage"

urlpatterns = [
    path("", stub, name="home"),
    path("teachers/", stub, name="teachers"),
    path("teachers/new/", stub, name="teacher_create"),
    path("teachers/<int:pk>/", stub, name="teacher_edit"),
    path("teachers/<int:pk>/password/", stub, name="teacher_password"),
    path("teachers/<int:pk>/active/", stub, name="teacher_active"),
    path("settings/", stub, name="settings"),
]
