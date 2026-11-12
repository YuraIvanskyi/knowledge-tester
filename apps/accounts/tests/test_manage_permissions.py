"""Who may open which /manage/ page: anonymous -> login, teacher -> 404, admin -> in."""

import pytest
from django.test import Client
from django.urls import reverse

GET_PAGES = ["manage:home", "manage:teachers", "manage:teacher_create", "manage:settings"]
GET_PAGES_WITH_PK = ["manage:teacher_edit", "manage:teacher_password"]
POST_ONLY = ["manage:teacher_active"]


def url_of(name, target):
    return (
        reverse(name, args=[target.pk]) if name in GET_PAGES_WITH_PK + POST_ONLY else reverse(name)
    )


ALL_NAMES = GET_PAGES + GET_PAGES_WITH_PK + POST_ONLY


@pytest.mark.parametrize("name", ALL_NAMES)
@pytest.mark.parametrize("method", ["get", "post"])
def test_anonymous_is_sent_to_login(anon_client, teacher, name, method):
    url = url_of(name, teacher)
    response = getattr(anon_client, method)(url)
    assert response.status_code == 302
    assert response["Location"] == f"{reverse('accounts:login')}?next={url}"


@pytest.mark.parametrize("name", ALL_NAMES)
@pytest.mark.parametrize("method", ["get", "post"])
def test_teacher_gets_404(teacher_c, teacher, name, method):
    response = getattr(teacher_c, method)(url_of(name, teacher))
    assert response.status_code == 404


@pytest.mark.parametrize("name", GET_PAGES + GET_PAGES_WITH_PK)
def test_admin_can_open_pages(admin_client, teacher, name):
    assert admin_client.get(url_of(name, teacher)).status_code == 200


def test_active_toggle_rejects_get_for_admin(admin_client, teacher):
    response = admin_client.get(reverse("manage:teacher_active", args=[teacher.pk]))
    assert response.status_code == 405


def test_unknown_account_is_404_for_admin(admin_client):
    for name in ("manage:teacher_edit", "manage:teacher_password"):
        assert admin_client.get(reverse(name, args=[99999])).status_code == 404
    assert admin_client.post(reverse("manage:teacher_active", args=[99999])).status_code == 404


def test_teacher_cannot_change_anything(teacher_c, teacher, other_teacher):
    teacher_c.post(
        reverse("manage:teacher_edit", args=[other_teacher.pk]),
        {"display_name": "Hacked", "role": "admin", "is_active": "on"},
    )
    teacher_c.post(reverse("manage:teacher_active", args=[other_teacher.pk]), {"active": "0"})
    teacher_c.post(
        reverse("manage:teacher_password", args=[other_teacher.pk]),
        {"password1": "Maple-river-42x", "password2": "Maple-river-42x"},
    )
    teacher_c.post(reverse("manage:settings"), {"school_name": "Mine"})
    other_teacher.refresh_from_db()
    assert other_teacher.role == "teacher" and other_teacher.is_active
    assert other_teacher.check_password("pw-for-tests-123")
    from apps.accounts.models import SystemSettings

    assert SystemSettings.load().school_name == ""


def test_demoted_admin_loses_access(admin_client, second_admin):
    other = Client()
    other.force_login(second_admin)
    assert other.get(reverse("manage:home")).status_code == 200
    response = admin_client.post(
        reverse("manage:teacher_edit", args=[second_admin.pk]),
        {"display_name": "Second", "role": "teacher", "is_active": "on"},
    )
    assert response.status_code == 302
    assert other.get(reverse("manage:home")).status_code == 404


def test_csrf_is_enforced(admin_user, teacher):
    client = Client(enforce_csrf_checks=True)
    client.force_login(admin_user)
    for name in ("manage:teacher_active", "manage:teacher_password", "manage:teacher_edit"):
        assert client.post(reverse(name, args=[teacher.pk])).status_code == 403
    assert client.post(reverse("manage:teacher_create")).status_code == 403
    assert client.post(reverse("manage:settings")).status_code == 403
    teacher.refresh_from_db()
    assert teacher.is_active


def test_manage_link_is_shown_to_admins_only(admin_client, teacher_c):
    manage_url = reverse("manage:home")
    assert f'href="{manage_url}"' in admin_client.get(reverse("core:dashboard")).content.decode()
    assert f'href="{manage_url}"' not in teacher_c.get(reverse("core:dashboard")).content.decode()


def test_admin_decorator_works_on_any_view(rf, teacher, admin_user):
    from django.http import Http404, HttpResponse

    from apps.accounts.permissions import admin_required

    @admin_required
    def view(request):
        return HttpResponse("ok")

    request = rf.get("/x/")
    request.user = teacher
    with pytest.raises(Http404):
        view(request)
    request.user = admin_user
    assert view(request).status_code == 200
