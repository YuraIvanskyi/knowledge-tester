"""First run: the first account is created in the browser, on the host computer only."""

import pytest
from django.test import Client
from django.urls import reverse

from apps.accounts.models import User
from tests.test_offline import csp_violations, external_urls

pytestmark = pytest.mark.django_db

SETUP = "/accounts/setup/"


def data(strong_password, **changes):
    values = {
        "display_name": "Olena Kovalenko",
        "username": "olena",
        "password1": strong_password,
        "password2": strong_password,
    }
    values.update(changes)
    return values


def test_a_fresh_install_leads_the_teacher_to_setup(anon_client):
    response = anon_client.get("/teach/", follow=True)
    assert response.redirect_chain[-1][0] == SETUP
    html = response.content.decode()
    assert 'name="username"' in html and 'name="password2"' in html
    assert external_urls(html) == [] and csp_violations(html) == []
    assert "<script" not in html


def test_setup_creates_an_admin_and_logs_in(anon_client, strong_password):
    response = anon_client.post(SETUP, data(strong_password))
    assert response["Location"] == reverse("core:dashboard")
    user = User.objects.get()
    assert user.username == "olena" and user.display_name == "Olena Kovalenko"
    assert user.is_admin_role and user.is_superuser and user.is_staff
    assert user.check_password(strong_password)
    assert anon_client.get(reverse("core:dashboard")).status_code == 200
    assert anon_client.get(reverse("manage:home")).status_code == 200


@pytest.mark.parametrize(
    "changes",
    [
        {"password2": "Something-else-9"},
        {"password1": "short", "password2": "short"},
        {"password1": "", "password2": ""},
        {"username": ""},
        {"username": "has spaces"},
        {"display_name": "   "},
    ],
)
def test_bad_input_creates_nothing(anon_client, strong_password, changes):
    response = anon_client.post(SETUP, data(strong_password, **changes))
    assert response.status_code == 200
    assert not User.objects.exists()
    assert 'class="errorlist"' in response.content.decode()


def test_another_device_never_gets_the_form(strong_password):
    phone = Client(REMOTE_ADDR="192.168.1.57")
    response = phone.get(SETUP)
    assert response.status_code == 403
    html = response.content.decode()
    assert "<form method" not in html and "only be created on the computer" in html
    assert phone.post(SETUP, data(strong_password)).status_code == 403
    assert not User.objects.exists()


def test_setup_is_gone_once_an_account_exists(anon_client, teacher, strong_password):
    assert anon_client.get(SETUP)["Location"] == reverse("accounts:login")
    response = anon_client.post(SETUP, data(strong_password))
    assert response["Location"] == reverse("accounts:login")
    assert list(User.objects.values_list("username", flat=True)) == ["teacher"]
    # and the login page is the login page again
    assert anon_client.get(reverse("accounts:login")).status_code == 200


def test_login_without_accounts_goes_to_setup(anon_client):
    assert anon_client.get(reverse("accounts:login"))["Location"] == SETUP
    response = anon_client.post(reverse("accounts:login"), {"username": "a", "password": "b"})
    assert response["Location"] == SETUP


def test_students_still_reach_the_landing_page_before_setup(anon_client):
    assert anon_client.get("/").status_code == 200
