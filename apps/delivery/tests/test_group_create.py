"""Creating a class (group-bound) session: the group dropdown and the PIN checkbox."""

import pytest
from django.urls import reverse

from apps.delivery import services
from apps.delivery.models import Sitting
from apps.people.models import Group

from .conftest import make_student

pytestmark = pytest.mark.django_db


@pytest.fixture
def create_url(revision):
    return reverse("delivery:create", args=[revision.pk])


@pytest.fixture
def teacher_client(client, teacher):
    client.force_login(teacher)
    return client


def test_dropdown_lists_only_my_active_classes(
    teacher_client, create_url, teacher, other_teacher, group, pupils
):
    Group.objects.create(owner=teacher, name="Old class", is_archived=True)
    Group.objects.create(owner=other_teacher, name="Someone else's")
    html = teacher_client.get(create_url).content.decode()
    assert 'name="group"' in html and 'name="use_pin"' in html
    assert "7-A (3 students), 1 without a PIN" in html  # Dan left, Cleo has no PIN
    assert "7-B (1 student)" in html
    assert "Old class" not in html and "Someone else" not in html
    assert "No class: students type their own name" in html
    assert "Ask for a personal PIN" in html


def test_creating_a_class_session(teacher_client, create_url, group, pupils):
    r = teacher_client.post(create_url, {"title": "Quiz", "group": group.pk, "use_pin": "on"})
    sitting = Sitting.objects.get()
    assert r.status_code == 302 and r["Location"] == reverse("delivery:share", args=[sitting.pk])
    assert sitting.group == group and sitting.use_pin is True


def test_class_without_pin(teacher_client, create_url, group, pupils):
    teacher_client.post(create_url, {"title": "Quiz", "group": group.pk})
    sitting = Sitting.objects.get()
    assert sitting.group == group and sitting.use_pin is False


def test_session_without_class_is_unchanged(teacher_client, create_url):
    teacher_client.post(create_url, {"title": "Quiz"})
    sitting = Sitting.objects.get()
    assert sitting.group is None and sitting.use_pin is False


def test_pin_needs_a_class(teacher_client, create_url):
    r = teacher_client.post(create_url, {"title": "Quiz", "use_pin": "on"})
    assert r.status_code == 200 and Sitting.objects.count() == 0
    assert "A personal PIN needs a class" in r.content.decode()


@pytest.mark.parametrize("kind", ["foreign", "archived", "garbage", "missing"])
def test_group_must_be_my_own_active_class(
    teacher_client, create_url, teacher, other_teacher, kind
):
    foreign = Group.objects.create(owner=other_teacher, name="Not mine")
    archived = Group.objects.create(owner=teacher, name="Archived", is_archived=True)
    value = {
        "foreign": foreign.pk,
        "archived": archived.pk,
        "garbage": "abc",
        "missing": 99999,
    }[kind]
    r = teacher_client.post(create_url, {"title": "Quiz", "group": value})
    assert r.status_code == 200 and Sitting.objects.count() == 0
    html = r.content.decode()
    assert "Choose one of your own classes" in html
    assert "Not mine" not in html  # never leaks the foreign name


def test_admin_gets_only_own_classes_in_the_dropdown(
    client, admin_user, teacher, revision, group, pupils
):
    own = Group.objects.create(owner=admin_user, name="Admin class")
    client.force_login(admin_user)
    url = reverse("delivery:create", args=[revision.pk])
    html = client.get(url).content.decode()
    assert "Admin class" in html and "7-A" not in html
    r = client.post(url, {"title": "x", "group": group.pk})  # a teacher's class: refused
    assert r.status_code == 200 and Sitting.objects.count() == 0
    assert client.post(url, {"title": "x", "group": own.pk}).status_code == 302


def test_no_classes_yet_points_to_the_people_page(teacher_client, create_url):
    html = teacher_client.get(create_url).content.decode()
    assert "You have no classes yet" in html and reverse("people:groups") in html


def test_warns_about_students_without_a_pin(teacher_client, create_url, group, pupils):
    r = teacher_client.post(
        create_url, {"title": "Quiz", "group": group.pk, "use_pin": "on"}, follow=True
    )
    html = r.content.decode()
    assert "1 student of this class has no PIN yet and cannot be picked" in html
    # and the share page keeps saying it
    assert "1 student has no PIN yet" in html


def test_no_pin_warning_without_pin_mode(teacher_client, create_url, group, pupils):
    r = teacher_client.post(create_url, {"title": "Quiz", "group": group.pk}, follow=True)
    assert "no PIN yet" not in r.content.decode()


def test_warns_about_an_empty_class(teacher_client, create_url, teacher):
    empty = Group.objects.create(owner=teacher, name="Empty")
    r = teacher_client.post(create_url, {"title": "Quiz", "group": empty.pk}, follow=True)
    assert "no active students" in r.content.decode()


def test_share_page_names_the_class(teacher_client, teacher, revision, group, pupils):
    sitting = services.create_sitting(
        revision=revision, user=teacher, title="Quiz", group=group, use_pin=True
    )
    html = teacher_client.get(reverse("delivery:share", args=[sitting.pk])).content.decode()
    assert "7-A" in html and "personal PIN required" in html
    assert reverse("delivery:link", args=[sitting.pk]) in html
    assert "SECRET-NOTE" not in html and "5829" not in html


def test_service_drops_pin_without_group(teacher, revision, group):
    plain = services.create_sitting(revision=revision, user=teacher, title="a", use_pin=True)
    assert plain.use_pin is False and plain.group is None
    pinned = services.create_sitting(
        revision=revision, user=teacher, title="b", group=group, use_pin=True
    )
    assert pinned.use_pin is True


def test_list_shows_the_class_and_link(teacher_client, teacher, revision, group, pupils):
    sitting = services.create_sitting(revision=revision, user=teacher, title="Quiz", group=group)
    make_student(teacher, group, "Late Joiner")
    html = teacher_client.get(reverse("delivery:list")).content.decode()
    assert "(7-A)" in html and reverse("delivery:link", args=[sitting.pk]) in html
