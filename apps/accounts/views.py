"""Login page and teacher self-registration."""

from __future__ import annotations

import logging

from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.views import LoginView as DjangoLoginView
from django.db import IntegrityError, transaction
from django.http import Http404
from django.shortcuts import redirect, render
from django.utils.translation import gettext as _
from django.views.decorators.cache import never_cache

from . import services
from .forms import RegisterForm
from .models import SystemSettings, User

logger = logging.getLogger(__name__)


def registration_is_open() -> SystemSettings | None:
    """The settings row if self-registration works right now, else None.

    An empty invite code counts as closed, so a half-configured switch never opens the door.
    Read-only: a GET never creates the settings row.
    """
    row = SystemSettings.objects.filter(pk=1).first()
    if row is not None and row.allow_registration and row.registration_code:
        return row
    return None


class LoginView(DjangoLoginView):
    """Django's login, plus a "Register" link when self-registration is on.

    A deactivated account gets the same "incorrect username or password" message as a wrong
    password (Django's backend refuses inactive users), so the page never says an account exists.
    """

    template_name = "registration/login.html"
    redirect_authenticated_user = True

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        try:
            context["registration_open"] = registration_is_open() is not None
        except Exception as error:  # noqa: BLE001 - logging in must work whatever the settings say
            logger.warning("Could not read the registration setting: %s", error)
            context["registration_open"] = False
        return context


@never_cache
def register(request):
    row = registration_is_open()
    if row is None:
        raise Http404
    if request.user.is_authenticated:
        return redirect("core:dashboard")

    client = services.client_ident(request)
    blocked = request.method == "POST" and (
        services.REGISTER_PER_CLIENT.blocked(client) or services.REGISTER_GLOBAL.blocked("all")
    )
    if blocked:
        context = {"form": None, "blocked": True}
        return render(request, "registration/register.html", context, status=429)

    form = RegisterForm(request.POST or None, expected_code=row.registration_code)
    if request.method == "POST":
        if form.is_valid():
            try:
                with transaction.atomic():
                    user = User.objects.create_user(
                        form.cleaned_data["username"],
                        password=form.new_password,
                        display_name=form.cleaned_data["display_name"],
                        role=User.Role.TEACHER,
                    )
            except IntegrityError:  # someone took the name a moment ago
                form.add_error("username", _("This username is already taken."))
            else:
                services.REGISTER_PER_CLIENT.clear(client)
                login(request, user, backend="django.contrib.auth.backends.ModelBackend")
                messages.success(request, _("Your account is ready. Welcome!"))
                return redirect("core:dashboard")
        elif form.code_wrong:
            services.REGISTER_PER_CLIENT.hit(client)
            services.REGISTER_GLOBAL.hit("all")
    return render(request, "registration/register.html", {"form": form, "blocked": False})
