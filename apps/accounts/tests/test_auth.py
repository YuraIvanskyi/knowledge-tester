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
