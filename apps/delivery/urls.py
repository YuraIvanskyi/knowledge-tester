from django.urls import path

from apps.core.stubs import not_implemented as stub

from . import views

app_name = "delivery"

urlpatterns = [
    path("", views.session_list, name="list"),
    path("new/<int:revision_pk>/", views.session_create, name="create"),
    path("<int:pk>/", views.session_share, name="share"),
    path("<int:pk>/stats/", views.session_stats, name="stats"),
    path("<int:pk>/close/", views.session_close, name="close"),
    path("<int:pk>/reopen/", views.session_reopen, name="reopen"),
    path("<int:pk>/delete/", views.session_delete, name="delete"),
    path("<int:pk>/link/", stub, name="link"),
]
