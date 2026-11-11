import pytest
from django.urls import reverse

from apps.assessments.models import Assessment, Project
from conftest import url_names_resolve


def test_landing_has_code_form(client):
    response = client.get(reverse("core:landing"))
    assert response.status_code == 200
    html = response.content.decode()
    assert 'name="code"' in html
    assert 'autocapitalize="characters"' in html
    assert reverse("accounts:login") in html
    # Anonymous visitors only see the brand, no teacher navigation.
    assert 'class="nav"' not in html


def test_landing_redirects_logged_in_teacher(teacher_client):
    response = teacher_client.get(reverse("core:landing"))
    assert response.status_code == 302
    assert response["Location"] == reverse("core:dashboard")


def test_healthz(client):
    response = client.get(reverse("core:healthz"))
    assert response.status_code == 200
    assert response.content == b"ok"


def test_dashboard_requires_login(client):
    response = client.get(reverse("core:dashboard"))
    assert response.status_code == 302
    assert response["Location"].startswith(reverse("accounts:login"))


def test_dashboard_empty_state(teacher_client):
    response = teacher_client.get(reverse("core:dashboard"))
    assert response.status_code == 200
    assert "No tests yet" in response.content.decode()


def test_nav_for_logged_in_user_has_logout_form(teacher_client):
    html = teacher_client.get(reverse("core:dashboard")).content.decode()
    assert 'class="nav"' in html
    assert f'action="{reverse("accounts:logout")}"' in html


@pytest.mark.skipif(not url_names_resolve("assessments:detail"), reason="needs assessments views")
def test_dashboard_lists_only_own_tests(teacher_client, teacher, other_teacher):
    mine = Project.objects.create(owner=teacher, title="Mine")
    theirs = Project.objects.create(owner=other_teacher, title="Theirs")
    Assessment.objects.create(project=mine, title="My algebra quiz")
    Assessment.objects.create(project=theirs, title="Secret quiz")
    html = teacher_client.get(reverse("core:dashboard")).content.decode()
    assert "My algebra quiz" in html
    assert "Secret quiz" not in html


@pytest.mark.skipif(not url_names_resolve("assessments:detail"), reason="needs assessments views")
def test_admin_dashboard_sees_all_tests(client_for, admin_user, other_teacher):
    project = Project.objects.create(owner=other_teacher, title="Theirs")
    Assessment.objects.create(project=project, title="Visible to admin")
    html = client_for(admin_user).get(reverse("core:dashboard")).content.decode()
    assert "Visible to admin" in html
