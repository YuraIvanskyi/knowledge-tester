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

from apps.core.lan import lan_ipv4_addresses

from . import services
from .forms import RegisterForm, SetupForm
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


LOCAL_ADDRESSES = ("127.0.0.1", "::1", "::ffff:127.0.0.1")


def needs_setup() -> bool:
    """True until the first account exists (a fresh data folder)."""
    return not User.objects.exists()


def _from_this_computer(request) -> bool:
    """Loopback, or one of this computer's own LAN addresses (the teacher typed the address that
    the start window printed instead of localhost: the connection still starts here)."""
    address = request.META.get("REMOTE_ADDR") or ""
    if address in LOCAL_ADDRESSES:
        return True
    try:
        return address in lan_ipv4_addresses()
    except Exception:  # noqa: BLE001 - never a reason to fail the page
        return False


@never_cache
def setup(request):
    """First run: create the first admin account in the browser, on the host computer only.

    Once any account exists the page is gone. A phone on the network that finds the server
    before the teacher does only sees where to go, never the form.
    """
    if not needs_setup():
        return redirect("accounts:login")
    if not _from_this_computer(request):
        return render(request, "registration/setup.html", {"form": None}, status=403)
    form = SetupForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            # Re-checked under the write lock: two browser tabs must not both create "the first".
            if User.objects.select_for_update().exists():
                return redirect("accounts:login")
            user = User.objects.create_superuser(
                form.cleaned_data["username"],
                password=form.new_password,
                display_name=form.cleaned_data["display_name"],
            )
        login(request, user, backend="django.contrib.auth.backends.ModelBackend")
        messages.success(request, _("Your account is ready. Welcome!"))
        return redirect("core:dashboard")
    return render(request, "registration/setup.html", {"form": form})


class LoginView(DjangoLoginView):
    """Django's login, plus a "Register" link when self-registration is on.

    A deactivated account gets the same "incorrect username or password" message as a wrong
    password (Django's backend refuses inactive users), so the page never says an account exists.
    """

    template_name = "registration/login.html"
    redirect_authenticated_user = True

    def dispatch(self, request, *args, **kwargs):
        if needs_setup():
            return redirect("accounts:setup")
        return super().dispatch(request, *args, **kwargs)

    def post(self, request, *args, **kwargs):
        if services.LOGIN_PER_CLIENT.blocked(services.client_ident(request)):
            form = self.get_form()
            form.add_error(None, _("Too many failed sign-in attempts. Wait a few minutes."))
            return self.render_to_response(self.get_context_data(form=form), status=429)
        return super().post(request, *args, **kwargs)

    def form_invalid(self, form):
        services.LOGIN_PER_CLIENT.hit(services.client_ident(self.request))
        return super().form_invalid(form)

    def form_valid(self, form):
        services.LOGIN_PER_CLIENT.clear(services.client_ident(self.request))
        return super().form_valid(form)

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
