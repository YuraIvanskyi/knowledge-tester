from django.urls import path

from . import views

app_name = "delivery"

urlpatterns = [
    path("", views.session_list, name="list"),
    path("new/", views.session_pick, name="pick"),
    path("new/<int:revision_pk>/", views.session_create, name="create"),
    path("<int:pk>/", views.session_share, name="share"),
    path("<int:pk>/stats/", views.session_stats, name="stats"),
    path("<int:pk>/close/", views.session_close, name="close"),
    path("<int:pk>/reopen/", views.session_reopen, name="reopen"),
    path("<int:pk>/delete/", views.session_delete, name="delete"),
    path("<int:pk>/link/", views.session_link, name="link"),
]
