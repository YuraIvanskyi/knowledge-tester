"""Offline/CSP guard for the admin area and the registration pages (workstream A)."""

from pathlib import Path

import pytest
from django.core.cache import cache
from django.test import Client
from django.urls import reverse

from apps.accounts.models import SystemSettings
from tests.test_offline import csp_violations, external_urls


@pytest.fixture(autouse=True)
def _fresh_cache():
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def registration_open():
    row = SystemSettings.load()
    row.allow_registration = True
    row.registration_code = "OPEN-SESAME"
    row.school_name = "Lyceum 5"
    row.save()


def responses(admin_user, teacher):
    admin = Client()
    admin.force_login(admin_user)
    anon = Client(REMOTE_ADDR="10.9.9.9")
    pages = [
        admin.get(reverse("manage:home")),
        admin.get(reverse("manage:teachers")),
        admin.get(reverse("manage:teachers"), {"q": "zzz"}),
        admin.get(reverse("manage:teacher_create")),
        admin.post(reverse("manage:teacher_create"), {"username": ""}),  # with form errors
        admin.get(reverse("manage:teacher_edit", args=[teacher.pk])),
        admin.get(reverse("manage:teacher_edit", args=[admin_user.pk])),  # locked fields
        admin.get(reverse("manage:teacher_password", args=[teacher.pk])),
        admin.post(reverse("manage:teacher_password", args=[teacher.pk]), {"password1": "x"}),
        admin.get(reverse("manage:settings")),
        admin.post(reverse("manage:settings"), {"registration_code": "x"}),
        anon.get(reverse("accounts:login")),
        anon.get(reverse("accounts:register")),
        anon.post(reverse("accounts:register"), {"code": "wrong"}),
    ]
    # the one-time password page
    admin.post(reverse("manage:teacher_password", args=[teacher.pk]), {"generate": "1"})
    pages.append(admin.get(reverse("manage:teacher_password", args=[teacher.pk])))
    # the page shown to a blocked client
    for _n in range(5):
        anon.post(reverse("accounts:register"), {"code": "wrong"})
    blocked = anon.post(reverse("accounts:register"), {"code": "wrong"})
    assert blocked.status_code == 429
    pages.append(blocked)
    return pages


def test_manage_and_register_pages_are_offline_and_csp_clean(
    admin_user, teacher, registration_open
):
    for response in responses(admin_user, teacher):
        assert response.status_code in (200, 429), response.request["PATH_INFO"]
        html = response.content.decode()
        where = response.request["PATH_INFO"]
        assert external_urls(html) == [], where
        assert csp_violations(html) == [], where


def test_manage_css_is_loaded_from_static(admin_user):
    admin = Client()
    admin.force_login(admin_user)
    html = admin.get(reverse("manage:home")).content.decode()
    assert "/static/css/manage.css" in html
    css = Path(__file__).resolve().parent.parent / "static" / "css" / "manage.css"
    assert css.is_file() and css.stat().st_size > 0


def test_manage_pages_need_no_javascript(admin_user, teacher, registration_open):
    for response in responses(admin_user, teacher):
        assert "<script" not in response.content.decode()
