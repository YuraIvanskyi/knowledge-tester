"""Teacher can reopen a closed session and delete sessions."""

import pytest
from django.test import Client
from django.urls import reverse

from apps.delivery import services
from apps.delivery.models import Attempt, Sitting

from .conftest import start

pytestmark = pytest.mark.django_db


@pytest.fixture
def teacher_client(client, teacher):
    client.force_login(teacher)
    return client


def test_reopen_closed_session(teacher_client, sitting):
    services.close_sitting(sitting)
    url = reverse("delivery:reopen", args=[sitting.pk])
    assert teacher_client.get(url).status_code == 405  # POST only
    response = teacher_client.post(url)
    assert response["Location"] == reverse("delivery:share", args=[sitting.pk])
    sitting.refresh_from_db()
    assert sitting.status == Sitting.Status.OPEN and sitting.closed_at is None
    page = teacher_client.get(reverse("delivery:share", args=[sitting.pk])).content.decode()
    assert "Close session" in page and "Reopen session" not in page


def test_share_page_offers_reopen_only_when_closed(teacher_client, sitting):
    share = reverse("delivery:share", args=[sitting.pk])
    assert "Reopen session" not in teacher_client.get(share).content.decode()
    services.close_sitting(sitting)
    assert "Reopen session" in teacher_client.get(share).content.decode()


def test_reopening_an_open_session_changes_nothing(teacher_client, sitting):
    teacher_client.post(reverse("delivery:reopen", args=[sitting.pk]))
    sitting.refresh_from_db()
    assert sitting.status == Sitting.Status.OPEN


def test_students_can_join_again_after_reopen(teacher_client, sitting):
    first = Client()
    start(first, sitting, "Ann")
    services.close_sitting(sitting)
    late = Client()
    assert late.post(f"/s/{sitting.code}/", {"tf_name": "Late"}).status_code == 200  # closed page
    assert not sitting.attempts.filter(taker__name="Late").exists()

    teacher_client.post(reverse("delivery:reopen", args=[sitting.pk]))
    response = start(late, sitting, "Late")
    assert response.status_code == 302 and response["Location"].endswith("/take/")
    assert sitting.attempts.filter(taker__name="Late").exists()
    # the attempt auto-submitted at close stays finished
    ann = sitting.attempts.get(taker__name="Ann")
    assert ann.status == Attempt.Status.AUTO_SUBMITTED


def test_reopen_foreign_session_404(client, other_teacher, sitting):
    sitting.status = Sitting.Status.CLOSED
    sitting.save()
    client.force_login(other_teacher)
    assert client.post(reverse("delivery:reopen", args=[sitting.pk])).status_code == 404
    sitting.refresh_from_db()
    assert sitting.status == Sitting.Status.CLOSED


def test_delete_session_asks_then_deletes_with_attempts(teacher_client, sitting, revision):
    start(Client(), sitting, "Ann")
    start(Client(), sitting, "Bob")
    assert Attempt.objects.count() == 2
    url = reverse("delivery:delete", args=[sitting.pk])
    page = teacher_client.get(url)
    assert page.status_code == 200 and "2" in page.content.decode()
    assert Sitting.objects.count() == 1
    response = teacher_client.post(url)
    assert response["Location"] == reverse("delivery:list")
    assert not Sitting.objects.exists() and not Attempt.objects.exists()
    revision.refresh_from_db()  # the published test is untouched
    assert revision.pk
    assert teacher_client.get(f"/s/{sitting.code}/").status_code == 404


def test_delete_foreign_session_404(client, other_teacher, sitting):
    client.force_login(other_teacher)
    assert client.get(reverse("delivery:delete", args=[sitting.pk])).status_code == 404
    assert client.post(reverse("delivery:delete", args=[sitting.pk])).status_code == 404
    assert Sitting.objects.count() == 1


def test_admin_can_delete_any_session(client, admin_user, sitting):
    client.force_login(admin_user)
    client.post(reverse("delivery:delete", args=[sitting.pk]))
    assert not Sitting.objects.exists()


def test_login_required(client, sitting):
    for name in ("reopen", "delete"):
        response = client.post(reverse(f"delivery:{name}", args=[sitting.pk]))
        assert response.status_code == 302 and "login" in response["Location"]
    assert Sitting.objects.count() == 1


def test_list_links_to_delete(teacher_client, sitting):
    html = teacher_client.get(reverse("delivery:list")).content.decode()
    assert reverse("delivery:delete", args=[sitting.pk]) in html
