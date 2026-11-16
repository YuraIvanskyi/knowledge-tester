"""Teacher self-registration with an invite code."""

import pytest
from django.test import Client
from django.urls import reverse

from apps.accounts import forms
from apps.accounts.models import SystemSettings, User

pytestmark = pytest.mark.django_db

URL = reverse("accounts:register")
CODE = "OPEN-SESAME"


def text(response):
    return response.content.decode()


def data(**extra):
    payload = {
        "code": CODE,
        "username": "newbie",
        "display_name": "New Teacher",
        "password1": "Maple-river-42x",
        "password2": "Maple-river-42x",
    }
    payload.update(extra)
    return payload


# --- on / off -------------------------------------------------------------------------------


def test_register_is_404_when_off(anon_client):
    assert anon_client.get(URL).status_code == 404
    assert anon_client.post(URL, data()).status_code == 404
    assert not User.objects.filter(username="newbie").exists()


def test_register_is_404_when_on_without_a_code(anon_client):
    SystemSettings.objects.update_or_create(
        pk=1, defaults={"allow_registration": True, "registration_code": ""}
    )
    assert anon_client.get(URL).status_code == 404
    assert anon_client.post(URL, data(code="")).status_code == 404


def test_login_page_links_to_register_only_when_enabled(anon_client, teacher):
    login = reverse("accounts:login")
    assert URL not in text(anon_client.get(login))
    row = SystemSettings.load()
    row.allow_registration = True
    row.registration_code = CODE
    row.save()
    assert URL in text(anon_client.get(login))
    row.registration_code = ""  # switched on but no code: still closed
    row.save()
    assert URL not in text(anon_client.get(login))


def test_register_form_renders(anon_client, registration_on):
    response = anon_client.get(URL)
    html = text(response)
    assert response.status_code == 200
    for name in ("code", "username", "display_name", "password1", "password2"):
        assert f'name="{name}"' in html
    assert "csrfmiddlewaretoken" in html
    assert CODE not in html  # the invite code is never printed on the public page


# --- the happy path -------------------------------------------------------------------------


def test_register_creates_a_teacher_and_logs_in(anon_client, registration_on):
    response = anon_client.post(URL, data())
    assert response.status_code == 302 and response["Location"] == reverse("core:dashboard")
    user = User.objects.get(username="newbie")
    assert user.role == "teacher" and user.is_active
    assert not user.is_staff and not user.is_superuser
    assert user.display_name == "New Teacher"
    assert user.check_password("Maple-river-42x")
    assert anon_client.get(reverse("core:dashboard")).status_code == 200
    assert anon_client.get(reverse("manage:home")).status_code == 404  # not an admin


def test_register_never_makes_an_admin(anon_client, registration_on):
    anon_client.post(URL, data(role="admin", is_staff="on", is_superuser="on"))
    user = User.objects.get(username="newbie")
    assert user.role == "teacher" and not user.is_staff and not user.is_superuser


def test_invite_code_is_trimmed(anon_client, registration_on):
    assert anon_client.post(URL, data(code=f"  {CODE} ")).status_code == 302


def test_generate_is_ignored_when_registering(anon_client, registration_on):
    response = anon_client.post(URL, data(password1="", password2="", generate="1"))
    assert response.status_code == 200 and "Type a password." in text(response)
    assert "generate" not in text(response).split("Type a password.")[1][:40]
    assert not User.objects.filter(username="newbie").exists()


def test_logged_in_user_is_sent_to_dashboard(teacher_c, registration_on):
    response = teacher_c.get(URL)
    assert response.status_code == 302 and response["Location"] == reverse("core:dashboard")


# --- refusals -------------------------------------------------------------------------------


def test_wrong_code_creates_nothing(anon_client, registration_on):
    response = anon_client.post(URL, data(code="guess"))
    assert response.status_code == 200
    assert "invite code is not correct" in text(response)
    assert not User.objects.filter(username="newbie").exists()
    assert "_auth_user_id" not in anon_client.session


def test_missing_code_is_a_plain_required_error(anon_client, registration_on):
    response = anon_client.post(URL, data(code=""))
    html = text(response)
    assert response.status_code == 200 and "required" in html
    assert "not correct" not in html


def test_wrong_code_reveals_nothing_else(anon_client, teacher, registration_on):
    """Without the code, no word about usernames or passwords."""
    response = anon_client.post(
        URL, data(code="guess", username=teacher.username, password1="a", password2="b")
    )
    html = text(response)
    assert "invite code is not correct" in html
    assert "already taken" not in html
    assert "do not match" not in html and "too short" not in html


@pytest.mark.parametrize(
    "changes, message",
    [
        ({"username": "TEACHER"}, "already taken"),
        ({"username": "bad name!"}, "valid username"),
        ({"display_name": ""}, "required"),
        ({"password2": "different-Pass-9"}, "do not match"),
        ({"password1": "", "password2": ""}, "Type a password"),
        ({"password1": "short1", "password2": "short1"}, "too short"),
        ({"password1": "newbie123", "password2": "newbie123"}, "too similar"),
    ],
)
def test_right_code_still_validates_the_rest(
    anon_client, teacher, registration_on, changes, message
):
    count = User.objects.count()
    response = anon_client.post(URL, data(**changes))
    assert response.status_code == 200 and message in text(response)
    assert User.objects.count() == count
    # a rejected form does not echo the passwords back
    assert "Maple-river-42x" not in text(response)


def test_code_is_compared_in_constant_time(anon_client, registration_on, monkeypatch):
    calls = []
    real = forms.constant_time_compare

    def spy(a, b):
        calls.append((a, b))
        return real(a, b)

    monkeypatch.setattr(forms, "constant_time_compare", spy)
    anon_client.post(URL, data(code="nope"))
    assert calls == [("nope", CODE)]


# --- throttling -----------------------------------------------------------------------------


def test_wrong_codes_are_throttled_per_client(registration_on):
    client = Client(REMOTE_ADDR="10.0.0.5")
    for _n in range(5):
        assert client.post(URL, data(code="guess")).status_code == 200
    blocked = client.post(URL, data())  # even the right code is refused now
    assert blocked.status_code == 429
    assert "Too many wrong invite codes" in text(blocked)
    assert not User.objects.filter(username="newbie").exists()
    # another computer is not affected
    other = Client(REMOTE_ADDR="10.0.0.6")
    assert other.post(URL, data()).status_code == 302


def test_throttle_ends_after_the_window(registration_on):
    from django.core.cache import cache

    client = Client(REMOTE_ADDR="10.0.0.5")
    for _n in range(5):
        client.post(URL, data(code="guess"))
    assert client.post(URL, data()).status_code == 429
    cache.clear()  # what the expiry of the window amounts to
    assert client.post(URL, data()).status_code == 302


def test_other_form_errors_do_not_count_as_guesses(registration_on):
    client = Client(REMOTE_ADDR="10.0.0.5")
    for _n in range(8):
        client.post(URL, data(password2="different-Pass-9"))
    assert client.post(URL, data()).status_code == 302


def test_get_is_never_blocked(registration_on):
    client = Client(REMOTE_ADDR="10.0.0.5")
    for _n in range(5):
        client.post(URL, data(code="guess"))
    assert client.get(URL).status_code == 200


def test_global_throttle(registration_on, monkeypatch):
    from apps.accounts import services

    monkeypatch.setattr(services.REGISTER_GLOBAL, "limit", 3)
    for n in range(3):
        Client(REMOTE_ADDR=f"10.0.1.{n}").post(URL, data(code="guess"))
    assert Client(REMOTE_ADDR="10.0.9.9").post(URL, data()).status_code == 429


def test_throttle_class_counts_and_clears():
    from apps.accounts.services import Throttle

    throttle = Throttle("t", limit=2, window=60)
    assert not throttle.blocked("a")
    throttle.hit("a")
    throttle.hit("a")
    assert throttle.blocked("a") and not throttle.blocked("b")
    throttle.clear("a")
    assert not throttle.blocked("a")
    assert not throttle.blocked("fe80::1")
    throttle.hit("fe80::1")


# --- the login page ------------------------------------------------------------------------


def test_login_keeps_working(anon_client, teacher, password):
    response = anon_client.post(
        reverse("accounts:login"), {"username": "teacher", "password": password}
    )
    assert response.status_code == 302 and response["Location"] == reverse("core:dashboard")
