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


def test_dashboard_counts_only_own_people(teacher_client, teacher, other_teacher):
    from apps.people.models import Group, Student

    mine = Group.objects.create(owner=teacher, name="7-A")
    Student.objects.create(owner=teacher, group=mine, full_name="Іван Петренко")
    Student.objects.create(owner=teacher, group=mine, full_name="Олена Коваль", is_active=False)
    theirs = Group.objects.create(owner=other_teacher, name="8-B")
    Student.objects.create(owner=other_teacher, group=theirs, full_name="Хтось Інший")
    # Tests exist, so the summary line is rendered instead of the empty state.
    project = Project.objects.create(owner=teacher, title="Mine")
    Assessment.objects.create(project=project, title="Quiz")
    html = teacher_client.get(reverse("core:dashboard")).content.decode()
    assert "1 group" in html
    assert "1 student" in html
    assert reverse("people:groups") in html


def test_nav_shows_manage_only_to_admins(client_for, teacher, admin_user):
    manage = reverse("manage:home")
    assert manage not in client_for(teacher).get(reverse("core:dashboard")).content.decode()
    assert manage in client_for(admin_user).get(reverse("core:dashboard")).content.decode()


def test_dashboard_primary_action_opens_a_session_and_recent_tests_link_latest_revision(
    teacher_client, teacher
):
    import re

    from apps.assessments.models import Revision

    project = Project.objects.create(owner=teacher, title="Mine")
    published = Assessment.objects.create(
        project=project, title="Published quiz", status="published"
    )
    revision = Revision.objects.create(
        assessment=published, number=1, document={}, content_hash="a"
    )
    revision2 = Revision.objects.create(
        assessment=published, number=2, document={}, content_hash="b"
    )
    Assessment.objects.create(project=project, title="Draft quiz")
    html = teacher_client.get(reverse("core:dashboard")).content.decode()
    primary = re.findall(r'class="btn btn-primary" href="([^"]*)"', html)
    assert primary == [reverse("delivery:pick")]
    assert reverse("assessments:create") in html and reverse("assessments:import") in html
    assert reverse("delivery:create", args=[revision2.pk]) in html
    assert reverse("delivery:create", args=[revision.pk]) not in html
    # the "no open sessions" text leads to the chooser
    assert f'<a href="{reverse("delivery:pick")}">No open sessions' in html
