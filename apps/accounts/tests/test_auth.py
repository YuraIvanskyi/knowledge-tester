from django.test import Client
from django.urls import reverse


def test_login_page_renders(client):
    response = client.get(reverse("accounts:login"))
    assert response.status_code == 200
    html = response.content.decode()
    assert 'name="username"' in html and 'name="password"' in html


def test_login_redirects_to_dashboard(client, teacher, password):
    response = client.post(reverse("accounts:login"), {"username": "teacher", "password": password})
    assert response.status_code == 302
    assert response["Location"] == reverse("core:dashboard")


def test_login_honours_next(client, teacher, password):
    url = reverse("accounts:login") + "?next=/teach/"
    response = client.post(url, {"username": "teacher", "password": password, "next": "/teach/"})
    assert response["Location"] == "/teach/"


def test_wrong_password_shows_error(client, teacher):
    response = client.post(reverse("accounts:login"), {"username": "teacher", "password": "no"})
    assert response.status_code == 200
    assert "alert-bad" in response.content.decode()


def test_logout_is_post_only(teacher_client):
    assert teacher_client.get(reverse("accounts:logout")).status_code == 405
    response = teacher_client.post(reverse("accounts:logout"))
    assert response.status_code == 302
    assert response["Location"] == reverse("core:landing")
    assert teacher_client.get(reverse("core:dashboard")).status_code == 302


def test_superuser_gets_admin_role(admin_user):
    assert admin_user.is_admin_role


# --- throttle on wrong passwords --------------------------------------------------------------


def _wrong(client, username="teacher"):
    return client.post(reverse("accounts:login"), {"username": username, "password": "nope"})


def test_login_is_blocked_after_ten_wrong_passwords(client, teacher, password):
    for _ in range(10):
        assert _wrong(client).status_code == 200
    response = _wrong(client)
    assert response.status_code == 429
    assert "Too many failed sign-in attempts" in response.content.decode()
    # even the right password is refused while the block lasts
    right = client.post(reverse("accounts:login"), {"username": "teacher", "password": password})
    assert right.status_code == 429
    assert "_auth_user_id" not in client.session


def test_the_block_is_per_client_not_per_account(client, teacher, password):
    for _ in range(10):
        _wrong(client)
    other = Client(REMOTE_ADDR="10.0.0.7")  # another phone on the LAN
    response = other.post(reverse("accounts:login"), {"username": "teacher", "password": password})
    assert response.status_code == 302


def test_a_good_login_resets_the_count(client, teacher, password):
    for _ in range(9):
        _wrong(client)
    assert (
        client.post(
            reverse("accounts:login"), {"username": "teacher", "password": password}
        ).status_code
        == 302
    )
    client.logout()
    for _ in range(9):
        assert _wrong(client).status_code == 200
