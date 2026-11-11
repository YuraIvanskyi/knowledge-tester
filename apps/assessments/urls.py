from django.urls import path

from . import views

app_name = "assessments"

urlpatterns = [
    path("", views.test_list, name="list"),
    path("import/", views.import_test, name="import"),
    path("<int:pk>/", views.detail, name="detail"),
    path("<int:pk>/publish/", views.publish, name="publish"),
    path("<int:pk>/export/", views.export, name="export"),
]
