from django.urls import path

from . import editor_views, views

app_name = "assessments"

urlpatterns = [
    path("", views.test_list, name="list"),
    path("new/", editor_views.create, name="create"),
    path("import/", views.import_test, name="import"),
    path("<int:pk>/", views.detail, name="detail"),
    path("<int:pk>/publish/", views.publish, name="publish"),
    path("<int:pk>/delete/", editor_views.delete, name="delete"),
    path("<int:pk>/preview/", editor_views.preview, name="preview"),
    path("<int:pk>/export/", views.export, name="export"),
    path("<int:pk>/settings/", editor_views.test_settings, name="settings"),
    path(
        "<int:pk>/questions/new/<str:question_type>/",
        editor_views.question_new,
        name="question_new",
    ),
    path("<int:pk>/questions/<str:question_id>/", editor_views.question_edit, name="question_edit"),
    path(
        "<int:pk>/questions/<str:question_id>/delete/",
        editor_views.question_delete,
        name="question_delete",
    ),
    path(
        "<int:pk>/questions/<str:question_id>/move/",
        editor_views.question_move,
        name="question_move",
    ),
    path(
        "<int:pk>/questions/<str:question_id>/duplicate/",
        editor_views.question_duplicate,
        name="question_duplicate",
    ),
]
