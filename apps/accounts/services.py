"""Account rules shared by the admin area and self-registration (plan §14, KT-601)."""

from __future__ import annotations

from django.conf import settings
from django.contrib.auth import password_validation
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.utils.crypto import get_random_string
from django.utils.translation import gettext as _

from .models import User

# The project settings do not configure AUTH_PASSWORD_VALIDATORS (and are frozen), so without a
# fallback "Django's password validators" would silently validate nothing.
FALLBACK_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        "OPTIONS": {"min_length": 8},
    },
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# No look-alikes (0/o, 1/l/i), lower case only: easy to read out and to type on a phone.
PASSWORD_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"
CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
MIN_INVITE_CODE_LENGTH = 6


def validate_new_password(password: str, user: User | None = None) -> None:
    """Run Django's password validators (the project's list, else the fallback)."""
    if settings.AUTH_PASSWORD_VALIDATORS:
        validators = password_validation.get_default_password_validators()
    else:
        validators = password_validation.get_password_validators(FALLBACK_VALIDATORS)
    password_validation.validate_password(password, user, validators)


def generate_password(user: User | None = None) -> str:
    """A random password like ``k7mq-x4pn-r2dw`` that passes the validators."""
    while True:
        candidate = "-".join(get_random_string(4, PASSWORD_ALPHABET) for _part in range(3))
        try:
            validate_new_password(candidate, user)
        except ValidationError:  # practically never; try again
            continue
        return candidate


def generate_invite_code() -> str:
    """A random invite code like ``K7MQ-X4PN``."""
    return "-".join(get_random_string(4, CODE_ALPHABET) for _part in range(2))


def active_admins():
    return User.objects.filter(role=User.Role.ADMIN, is_active=True)


def access_change_error(
    target: User, *, acting: User, new_role: str, new_active: bool
) -> str | None:
    """Why the change of ``target`` to (role, active) is not allowed, or None if it is fine.

    Rules: you cannot deactivate or demote yourself, and the last active admin stays an admin.
    """
    if target.pk == acting.pk:
        if not new_active:
            return _("You cannot deactivate your own account.")
        if new_role != target.role:
            return _("You cannot change your own role. Ask another admin to do it.")
    removes_admin = (
        target.role == User.Role.ADMIN
        and target.is_active
        and (new_role != User.Role.ADMIN or not new_active)
    )
    if removes_admin and not active_admins().exclude(pk=target.pk).exists():
        return _("This is the last active admin. Make someone else an admin first.")
    return None


class Throttle:
    """Count events per client in the cache and block after ``limit`` within ``window`` seconds.

    The cache is per process (local memory), which is enough for one waitress process on a LAN.
    """

    def __init__(self, scope: str, limit: int, window: int):
        self.scope = scope
        self.limit = limit
        self.window = window

    def _key(self, ident: str) -> str:
        return f"kt-throttle:{self.scope}:{ident.replace(':', '_')}"

    def blocked(self, ident: str) -> bool:
        return cache.get(self._key(ident), 0) >= self.limit

    def hit(self, ident: str) -> None:
        key = self._key(ident)
        cache.add(key, 0, self.window)  # starts the window only for the first failure
        try:
            cache.incr(key)
        except ValueError:  # expired between add and incr
            cache.set(key, 1, self.window)

    def clear(self, ident: str) -> None:
        cache.delete(self._key(ident))


def client_ident(request) -> str:
    """The address the TCP connection came from; X-Forwarded-For is never trusted here."""
    return request.META.get("REMOTE_ADDR") or "unknown"


# Wrong passwords at the login page: 10 per client per 5 minutes. Per client, not per account:
# a per-account lock would let any student on the network lock the teacher out.
LOGIN_PER_CLIENT = Throttle("login", limit=10, window=5 * 60)

# Wrong invite codes: 5 per client per 10 minutes, and 60 per hour across all clients.
REGISTER_PER_CLIENT = Throttle("register", limit=5, window=10 * 60)
REGISTER_GLOBAL = Throttle("register-all", limit=60, window=60 * 60)
