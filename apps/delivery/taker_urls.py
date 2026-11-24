from django.urls import path

from apps.core.stubs import not_implemented

from . import taker_views as views

app_name = "taker"

urlpatterns = [
    path("enter/", views.enter, name="enter"),
    path("<str:code>/", views.session, name="session"),
    path("<str:code>/take/", views.take, name="take"),
    path("<str:code>/save/", views.save, name="save"),
    path("<str:code>/submit/", views.submit, name="submit"),
    path("<str:code>/done/", views.done, name="done"),
    path("<str:code>/away/", views.away, name="away"),
    # POST: forget this browser's attempt so the next student can start on the same device.
    path("<str:code>/another/", not_implemented, name="another"),
]
