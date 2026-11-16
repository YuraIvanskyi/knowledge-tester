"""Admin area URLs (prefix /manage/, workstream A). Every view is wrapped in `admin_required`."""

from django.urls import path

from . import manage_views as views

app_name = "manage"

urlpatterns = [
    path("", views.home, name="home"),
    path("teachers/", views.teachers, name="teachers"),
    path("teachers/new/", views.teacher_create, name="teacher_create"),
    path("teachers/<int:pk>/", views.teacher_edit, name="teacher_edit"),
    path("teachers/<int:pk>/password/", views.teacher_password, name="teacher_password"),
    path("teachers/<int:pk>/active/", views.teacher_active, name="teacher_active"),
    path("settings/", views.settings_page, name="settings"),
    path("backups/", views.backups, name="backups"),
    path("backups/new/", views.backup_create, name="backup_create"),
    path("backups/<str:name>", views.backup_download, name="backup_download"),
]
