from django.contrib.auth import views as auth_views
from django.urls import path

from apps.core.stubs import not_implemented as stub

app_name = "accounts"

urlpatterns = [
    path(
        "login/",
        auth_views.LoginView.as_view(
            template_name="registration/login.html", redirect_authenticated_user=True
        ),
        name="login",
    ),
    # Logout accepts POST only (Django 5+); the nav bar renders a small form.
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("register/", stub, name="register"),
]
