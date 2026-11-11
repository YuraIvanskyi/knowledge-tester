from django.urls import path

from . import taker_views as views

app_name = "taker"

urlpatterns = [
    path("enter/", views.enter, name="enter"),
    path("<str:code>/", views.session, name="session"),
    path("<str:code>/take/", views.take, name="take"),
    path("<str:code>/save/", views.save, name="save"),
    path("<str:code>/submit/", views.submit, name="submit"),
    path("<str:code>/done/", views.done, name="done"),
]
