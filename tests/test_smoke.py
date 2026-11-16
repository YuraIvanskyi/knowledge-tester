from django.urls import reverse


def test_root_responds(client):
    assert client.get("/").status_code == 200


def test_healthz(client):
    assert client.get("/healthz").status_code == 200


def test_login_page_renders(client, teacher):
    assert client.get(reverse("accounts:login")).status_code == 200


def test_teach_redirects_anonymous(client):
    response = client.get("/teach/")
    assert response.status_code == 302
    assert "/accounts/login/" in response["Location"]


def test_login_then_dashboard(client, teacher, password):
    response = client.post(
        reverse("accounts:login"), {"username": teacher.username, "password": password}, follow=True
    )
    assert response.redirect_chain[-1][0] == "/teach/"
    assert response.status_code == 200
