"""UX review wave, workstream B: close confirmation, session chooser, ?group=, share screen."""

import re
from pathlib import Path

import pytest
from django.contrib.messages import get_messages
from django.test import Client
from django.urls import reverse

from apps.assessments.models import Assessment, Revision
from apps.delivery import services
from apps.delivery.models import Attempt, Sitting
from apps.people.models import Group

from .conftest import make_document, make_revision, start

pytestmark = pytest.mark.django_db


@pytest.fixture
def teacher_client(client, teacher):
    client.force_login(teacher)
    return client


# --- UX-02: closing asks while students are still working ---------------------------------


def test_close_with_students_working_asks_first(teacher_client, sitting, grade_calls):
    start(Client(), sitting, "Ann")
    start(Client(), sitting, "Bob")
    url = reverse("delivery:close", args=[sitting.pk])
    response = teacher_client.post(url)
    assert response.status_code == 200
    html = response.content.decode()
    assert "2 students are still working" in html
    assert 'name="confirm" value="1"' in html and "Cancel" in html
    sitting.refresh_from_db()
    assert sitting.status == Sitting.Status.OPEN
    assert sitting.attempts.filter(status=Attempt.Status.IN_PROGRESS).count() == 2
    assert grade_calls == []


def test_close_confirmed_submits_and_reports_the_count(teacher_client, sitting):
    start(Client(), sitting, "Ann")
    response = teacher_client.post(reverse("delivery:close", args=[sitting.pk]), {"confirm": "1"})
    assert response["Location"] == reverse("delivery:share", args=[sitting.pk])
    sitting.refresh_from_db()
    assert sitting.status == Sitting.Status.CLOSED
    message = [str(m) for m in get_messages(response.wsgi_request)]
    assert message == ["Session closed. 1 unfinished attempt was submitted automatically."]


def test_close_with_nobody_working_closes_at_once(teacher_client, sitting):
    start(Client(), sitting, "Ann")
    attempt = sitting.attempts.get()
    attempt.status = Attempt.Status.SUBMITTED
    attempt.save()
    response = teacher_client.post(reverse("delivery:close", args=[sitting.pk]))
    assert response.status_code == 302
    sitting.refresh_from_db()
    assert sitting.status == Sitting.Status.CLOSED
    assert [str(m) for m in get_messages(response.wsgi_request)] == ["Session closed."]


def test_close_without_attempts_closes_at_once(teacher_client, sitting):
    response = teacher_client.post(reverse("delivery:close", args=[sitting.pk]))
    assert response.status_code == 302
    sitting.refresh_from_db()
    assert sitting.status == Sitting.Status.CLOSED


def test_close_is_post_only_and_404_for_foreign(client, other_teacher, teacher_client, sitting):
    start(Client(), sitting, "Ann")
    url = reverse("delivery:close", args=[sitting.pk])
    assert teacher_client.get(url).status_code == 405
    assert teacher_client.get(url + "?confirm=1").status_code == 405
    client.force_login(other_teacher)
    assert client.post(url).status_code == 404
    assert client.post(url, {"confirm": "1"}).status_code == 404
    sitting.refresh_from_db()
    assert sitting.status == Sitting.Status.OPEN


def test_share_page_close_is_plain_and_delete_comes_last(teacher_client, sitting):
    html = teacher_client.get(reverse("delivery:share", args=[sitting.pk])).content.decode()
    close = html.index("Close session")
    assert "btn-danger" not in html[close - 80 : close]
    assert html.index("All sessions") < html.index(reverse("delivery:delete", args=[sitting.pk]))


# --- UX-06: the chooser and ?group= -----------------------------------------------------------


def test_pick_requires_login(client):
    response = client.get(reverse("delivery:pick"))
    assert response.status_code == 302 and "/accounts/login/" in response["Location"]
    assert reverse("delivery:pick") == "/teach/sessions/new/"


def test_pick_lists_own_published_tests_newest_first(teacher_client, teacher, other_teacher):
    old = make_revision(teacher, title="Old test")
    new = make_revision(teacher, title="New test")
    newer = Revision.objects.create(
        assessment=new.assessment, number=2, document=make_document(), content_hash="y"
    )
    Assessment.objects.filter(pk=new.assessment_id).update(has_unpublished_changes=True)
    make_revision(other_teacher, title="Foreign test")
    # a draft that was never published has no revision at all
    Assessment.objects.create(project=old.assessment.project, title="Draft only", document={})
    html = teacher_client.get(reverse("delivery:pick")).content.decode()
    assert "Foreign test" not in html and "Draft only" not in html
    assert html.index("New test") < html.index("Old test")
    # the link goes to the LATEST revision, and the page says what version that is
    assert reverse("delivery:create", args=[newer.pk]) in html
    assert reverse("delivery:create", args=[new.pk]) not in html
    assert reverse("delivery:create", args=[old.pk]) in html
    assert "Unpublished changes" in html
    assert "5 questions" in html and "10 min" in html


def test_pick_empty_state_links_to_tests(teacher_client):
    html = teacher_client.get(reverse("delivery:pick")).content.decode()
    assert "no published tests" in html and reverse("assessments:list") in html


def test_pick_admin_sees_all_tests(client, admin_user, teacher):
    make_revision(teacher, title="Zebra test")
    client.force_login(admin_user)
    assert "Zebra test" in client.get(reverse("delivery:pick")).content.decode()


def test_pick_query_count_does_not_grow(teacher_client, teacher, django_assert_max_num_queries):
    for i in range(6):
        make_revision(teacher, title=f"T{i}")
    with django_assert_max_num_queries(12):
        assert teacher_client.get(reverse("delivery:pick")).status_code == 200


def test_pick_passes_the_group_on(teacher_client, revision, group):
    html = teacher_client.get(reverse("delivery:pick"), {"group": group.pk}).content.decode()
    assert reverse("delivery:create", args=[revision.pk]) + f"?group={group.pk}" in html
    assert group.name in html


@pytest.mark.parametrize("raw", ["abc", "-1", "99999", "1;2", "", "9" * 40, "%00"])
def test_pick_ignores_bad_group(teacher_client, revision, raw):
    response = teacher_client.get(reverse("delivery:pick"), {"group": raw})
    assert response.status_code == 200
    assert not re.search(r"new/\d+/\?group=", response.content.decode())


def test_pick_ignores_a_foreign_group(teacher_client, other_teacher, revision):
    foreign = Group.objects.create(owner=other_teacher, name="Secret class")
    response = teacher_client.get(reverse("delivery:pick"), {"group": foreign.pk})
    html = response.content.decode()
    assert (
        response.status_code == 200
        and "Secret class" not in html
        and not re.search(r"new/\d+/\?group=", html)
    )


def test_create_preselects_own_group(teacher_client, revision, group):
    url = reverse("delivery:create", args=[revision.pk])
    html = teacher_client.get(url, {"group": group.pk}).content.decode()
    assert f'<option value="{group.pk}" selected>' in html
    assert f'<option value="{group.pk}" selected>' not in teacher_client.get(url).content.decode()


@pytest.mark.parametrize("raw", ["abc", "0", "424242", "1e3", "-5"])
def test_create_ignores_bad_group(teacher_client, revision, group, raw):
    response = teacher_client.get(reverse("delivery:create", args=[revision.pk]), {"group": raw})
    assert response.status_code == 200 and 'value="" selected>' in response.content.decode()


def test_create_ignores_a_foreign_group(teacher_client, other_teacher, revision):
    foreign = Group.objects.create(owner=other_teacher, name="Secret class")
    response = teacher_client.get(
        reverse("delivery:create", args=[revision.pk]), {"group": foreign.pk}
    )
    html = response.content.decode()
    assert (
        response.status_code == 200 and "Secret class" not in html and 'value="" selected>' in html
    )


def test_create_ignores_an_archived_group(teacher_client, revision, group):
    group.is_archived = True
    group.save()
    url = reverse("delivery:create", args=[revision.pk])
    response = teacher_client.get(url, {"group": group.pk})
    assert 'value="" selected>' in response.content.decode()


def test_list_has_primary_button_and_phone_card_classes(teacher_client, sitting):
    html = teacher_client.get(reverse("delivery:list")).content.decode()
    assert f'class="btn btn-primary" href="{reverse("delivery:pick")}"' in html
    assert "table-compact" in html and 'class="cell-title"' in html and "cell-actions" in html
    # Delete is the last link of the actions cell
    actions = html[html.index("cell-actions") :]
    assert actions.index(reverse("delivery:delete", args=[sitting.pk])) > actions.index(
        reverse("delivery:link", args=[sitting.pk])
    )


def test_list_empty_state_has_the_same_button(teacher_client):
    html = teacher_client.get(reverse("delivery:list")).content.decode()
    assert "No sessions yet" in html
    assert html.count(reverse("delivery:pick")) >= 2  # header button and the empty state


# --- UX-16: share screen ----------------------------------------------------------------------


def test_share_url_is_one_line_sized(teacher_client, sitting):
    html = teacher_client.get(reverse("delivery:share", args=[sitting.pk])).content.decode()
    assert 'class="big-url mono len-' in html
    assert "?present=1" in html and "Presentation mode" in html


def test_present_mode_hides_nav_and_takers(teacher_client, sitting):
    start(Client(), sitting, "Ann Lee")
    url = reverse("delivery:share", args=[sitting.pk])
    html = teacher_client.get(url, {"present": "1"}).content.decode()
    assert 'class="big-code"' in html and sitting.code in html and "<svg" in html
    assert 'id="c-joined"' in html and "Back to the session page" in html
    assert 'class="nav"' not in html
    assert "takers-table" not in html and "Ann Lee" not in html
    assert "Close session" not in html and reverse("delivery:delete", args=[sitting.pk]) not in html
    normal = teacher_client.get(url).content.decode()
    assert 'class="nav"' in normal and "Ann Lee" in normal


def test_present_mode_keeps_permissions(client, other_teacher, sitting):
    client.force_login(other_teacher)
    url = reverse("delivery:share", args=[sitting.pk])
    assert client.get(url, {"present": "1"}).status_code == 404


def test_takers_table_uses_the_card_pattern(teacher_client, sitting):
    start(Client(), sitting, "Done Dan")
    start(Client(), sitting, "Busy Bea")
    done = sitting.attempts.get(taker__name="Done Dan")
    done.status = Attempt.Status.SUBMITTED
    done.save()
    html = teacher_client.get(reverse("delivery:share", args=[sitting.pk])).content.decode()
    assert 'table table-compact takers" id="takers-table"' in html
    assert html.count('<td class="cell-title">') == 2
    assert html.count('<span class="status-ok">Submitted</span>') == 1
    assert ">In progress</td>" in html


def test_share_js_builds_the_same_markup_as_the_template():
    js = (Path(__file__).resolve().parents[3] / "static/js/share.js").read_text(encoding="utf-8")
    for needle in ('"cell-title"', '"status-ok"', '"num"', "in_progress", "data-label", '"muted"'):
        assert needle in js


def test_closing_through_services_is_unchanged(sitting):
    start(Client(), sitting, "Ann")
    assert services.close_sitting(sitting) == 1
