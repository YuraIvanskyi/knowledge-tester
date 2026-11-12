"""The taker side of a class session: pick your name from the list (no PIN)."""

import json
import re

import pytest
from django.test import Client
from django.urls import reverse

from apps.delivery import roster, services
from apps.delivery.models import Attempt, Sitting
from apps.people.models import Group, Student

from .conftest import make_document, make_revision, make_student, pick, start

pytestmark = pytest.mark.django_db


def token_of(html: str) -> str:
    return re.search(r'name="attempt_token" value="([0-9a-f-]{36})"', html).group(1)


def autosave(client, sitting, token, answers=None, **details):
    payload = {"answers": answers or {"q1": ["a"]}, "unstarted": True, "attempt_token": token}
    return client.post(
        f"/s/{sitting.code}/save/",
        data=json.dumps({**payload, **details}),
        content_type="application/json",
    )


def submit(client, sitting, token, **details):
    data = {"unstarted": "1", "attempt_token": token, "form_sent": "1", "q_q1": ["a"], **details}
    return client.post(f"/s/{sitting.code}/submit/", data)


# --- the landing page --------------------------------------------------------------------------


def test_landing_page_has_a_class_list_instead_of_a_name_box(client, group_sitting, pupils):
    html = client.get(f"/s/{group_sitting.code}/").content.decode()
    assert 'name="student"' in html and 'name="tf_name"' not in html
    assert 'name="tf_class"' in html  # the other taker fields are still asked
    assert 'name="q_q1"' in html  # the test itself is the landing page
    assert 'name="pin"' not in html
    assert "js/namepicker.js" in html
    names = re.findall(r'<option value="\d+"[^>]*>([^<]+)</option>', html)
    assert names == ["Ann Lee", "Bob Ray", "Cleo Fox"]  # active members of this class, by name
    assert "Dan Gone" not in html and "Eve Stone" not in html


def test_class_list_shows_names_only(client, group_sitting, pupils):
    html = client.get(f"/s/{group_sitting.code}/").content.decode()
    for secret in ("SECRET-NOTE", "5829", "7314", "9065", "1357", "ZEBRA-ACCEPT", "SECRET-RUBRIC"):
        assert secret not in html
    ids = re.findall(r'<option value="(\d+)"', html)
    assert set(ids) == {str(pupils[k].pk) for k in ("ann", "bob", "cleo")}


def test_list_is_sorted_with_ukrainian_alphabet(teacher, revision):
    group = Group.objects.create(owner=teacher, name="9-Б")
    for name in ("Ярема Іваненко", "Їжак Петро", "Іван Шевчук", "Ґанна Коваль", "Андрій Бойко"):
        make_student(teacher, group, name)
    sitting = services.create_sitting(revision=revision, user=teacher, title="t", group=group)
    names = [o["name"] for o in roster.picker_options(sitting)]
    assert names == ["Андрій Бойко", "Ґанна Коваль", "Іван Шевчук", "Їжак Петро", "Ярема Іваненко"]


def test_plain_start_form_also_has_the_list(client, group_sitting, pupils):
    r = client.post(f"/s/{group_sitting.code}/", {"tf_class": "7"})  # nobody picked
    html = r.content.decode()
    assert r.status_code == 200 and "Please choose your name from the list" in html
    assert 'name="student"' in html and 'name="tf_name"' not in html
    assert group_sitting.attempts.count() == 0


def test_closed_session_hides_the_class_list(client, group_sitting, pupils):
    services.close_sitting(group_sitting)
    r = client.get(f"/s/{group_sitting.code}/")
    html = r.content.decode()
    assert r.status_code == 200 and "closed" in html.lower()
    assert "Ann Lee" not in html and 'name="student"' not in html
    r = pick(client, group_sitting, pupils["ann"])
    assert r.status_code == 200 and group_sitting.attempts.count() == 0
    assert "Ann Lee" not in r.content.decode()


def test_non_group_session_is_unchanged(client, sitting, pupils):
    html = client.get(f"/s/{sitting.code}/").content.decode()
    assert 'name="tf_name"' in html and 'name="student"' not in html
    assert "Ann Lee" not in html and "namepicker" not in html
    start(client, sitting, name="Free Typed", student=pupils["ann"].pk)  # a stray field is ignored
    attempt = sitting.attempts.get()
    assert attempt.student is None and attempt.taker["name"] == "Free Typed"


def test_query_budget_of_the_landing_page(client, group_sitting, django_assert_max_num_queries):
    with django_assert_max_num_queries(6):
        assert client.get(f"/s/{group_sitting.code}/").status_code == 200


# --- starting an attempt, all three paths ------------------------------------------------------


def test_start_form_links_the_student(client, group_sitting, pupils):
    r = pick(client, group_sitting, pupils["ann"], tf_class="7-A", tf_name="Hacker")
    assert r.status_code == 302 and r["Location"] == f"/s/{group_sitting.code}/take/"
    attempt = group_sitting.attempts.get()
    assert attempt.student == pupils["ann"]
    assert attempt.taker == {"name": "Ann Lee", "class": "7-A"}  # typed name is ignored
    assert client.get(f"/s/{group_sitting.code}/take/").status_code == 200


def test_autosave_starts_the_attempt_with_the_student(client, group_sitting, pupils):
    html = client.get(f"/s/{group_sitting.code}/").content.decode()
    r = autosave(client, group_sitting, token_of(html), student=str(pupils["bob"].pk))
    assert r.json()["started"] is True
    attempt = group_sitting.attempts.get()
    assert attempt.student == pupils["bob"] and attempt.taker["name"] == "Bob Ray"
    assert f"kt_attempt_{group_sitting.code}" in r.cookies


def test_autosave_without_a_pick_does_not_start(client, group_sitting, pupils):
    html = client.get(f"/s/{group_sitting.code}/").content.decode()
    r = autosave(client, group_sitting, token_of(html))
    assert r.json()["started"] is False
    assert "Please choose your name from the list." in r.json()["errors"]
    assert group_sitting.attempts.count() == 0


def test_submit_starts_the_attempt_with_the_student(client, group_sitting, pupils, grade_calls):
    token = token_of(client.get(f"/s/{group_sitting.code}/").content.decode())
    r = submit(client, group_sitting, token, student=str(pupils["ann"].pk))
    assert r["Location"] == f"/s/{group_sitting.code}/done/"
    attempt = group_sitting.attempts.get()
    assert attempt.student == pupils["ann"] and attempt.taker["name"] == "Ann Lee"
    assert str(attempt.token) == token and attempt.status == Attempt.Status.SUBMITTED
    assert grade_calls


def test_submit_with_a_missing_pick_rerenders_with_answers_kept(client, group_sitting, pupils):
    token = token_of(client.get(f"/s/{group_sitting.code}/").content.decode())
    r = submit(client, group_sitting, token, q_q4="kept-answer")
    html = r.content.decode()
    assert r.status_code == 200 and "Please choose your name from the list" in html
    assert 'value="kept-answer"' in html and token in html
    assert group_sitting.attempts.count() == 0


def test_picked_student_stays_selected_after_an_error(client, group_sitting, pupils):
    # a required taker field is empty -> error, the pick must survive the round trip
    group_sitting.revision.test["taker_fields"][1]["required"] = True
    revision = group_sitting.revision
    revision.document["test"]["taker_fields"][1]["required"] = True
    revision.save()
    token = token_of(client.get(f"/s/{group_sitting.code}/").content.decode())
    r = submit(client, group_sitting, token, student=str(pupils["bob"].pk))
    html = r.content.decode()
    assert "Please fill in: Class" in html
    assert f'<option value="{pupils["bob"].pk}" selected>' in html


@pytest.mark.parametrize(
    "who", ["other_class", "inactive", "other_teacher", "garbage", "negative", "unknown", "blank"]
)
@pytest.mark.parametrize("path", ["form", "autosave", "submit"])
def test_a_student_outside_the_class_is_rejected(
    client, group_sitting, pupils, other_teacher, who, path
):
    stranger = make_student(other_teacher, None, "Mallory Stranger")
    value = {
        "other_class": pupils["eve"].pk,
        "inactive": pupils["dan"].pk,
        "other_teacher": stranger.pk,
        "garbage": "1; DROP TABLE",
        "negative": -1,
        "unknown": 999999,
        "blank": "",
    }[who]
    token = token_of(client.get(f"/s/{group_sitting.code}/").content.decode())
    if path == "form":
        r = client.post(f"/s/{group_sitting.code}/", {"student": value})
        assert r.status_code == 200
    elif path == "autosave":
        assert autosave(client, group_sitting, token, student=value).json()["started"] is False
    else:
        assert submit(client, group_sitting, token, student=str(value)).status_code == 200
    assert group_sitting.attempts.count() == 0
    # nothing about the rejected student leaks into the answer
    assert "Mallory" not in client.get(f"/s/{group_sitting.code}/").content.decode()


def test_deleted_group_turns_into_a_free_name_session(client, group_sitting, pupils):
    Group.objects.filter(pk=group_sitting.group_id).delete()
    html = client.get(f"/s/{group_sitting.code}/").content.decode()
    assert 'name="tf_name"' in html and 'name="student"' not in html
    assert Sitting.objects.get(pk=group_sitting.pk).group is None


# --- max_attempts per student ------------------------------------------------------------------


def finish(client, sitting):
    client.post(f"/s/{sitting.code}/submit/", {"form_sent": "1", "q_q1": "a"})


def second_browser_attempt(sitting, student, path):
    """A different browser (no cookie) tries to start for the same student."""
    other = Client()
    token = token_of(other.get(f"/s/{sitting.code}/").content.decode())
    if path == "form":
        r = pick(other, sitting, student)
        return r.status_code == 302
    if path == "autosave":
        return autosave(other, sitting, token, student=str(student.pk)).json()["started"]
    r = submit(other, sitting, token, student=str(student.pk))
    return r.status_code == 302


@pytest.mark.parametrize("path", ["form", "autosave", "submit"])
def test_one_attempt_per_student_on_every_start_path(client, group_sitting, pupils, path):
    pick(client, group_sitting, pupils["ann"])
    finish(client, group_sitting)
    assert not second_browser_attempt(group_sitting, pupils["ann"], path)
    assert group_sitting.attempts.count() == 1
    assert second_browser_attempt(group_sitting, pupils["bob"], path)  # another student: fine
    assert group_sitting.attempts.count() == 2


def test_the_limit_message_is_shown(client, group_sitting, pupils):
    pick(client, group_sitting, pupils["ann"])
    r = pick(Client(), group_sitting, pupils["ann"])
    assert "You have already taken this test" in r.content.decode()


@pytest.mark.parametrize("path", ["form", "autosave", "submit"])
def test_an_in_progress_attempt_counts_too(client, group_sitting, pupils, path):
    pick(client, group_sitting, pupils["ann"])  # started, not finished
    assert not second_browser_attempt(group_sitting, pupils["ann"], path)


def test_max_attempts_two_allows_exactly_two(teacher, pupils, group):
    revision = make_revision(teacher, make_document(max_attempts=2))
    sitting = services.create_sitting(revision=revision, user=teacher, title="t", group=group)
    for expected in (True, True, False):
        assert second_browser_attempt(sitting, pupils["ann"], "form") is expected
    assert sitting.attempts.filter(student=pupils["ann"]).count() == 2


def test_voided_attempts_do_not_count(client, group_sitting, pupils):
    pick(client, group_sitting, pupils["ann"])
    Attempt.objects.update(status=Attempt.Status.VOIDED)
    assert second_browser_attempt(group_sitting, pupils["ann"], "form")


def test_an_unlinked_attempt_with_the_same_name_counts(group_sitting, pupils):
    services.start_attempt(group_sitting, {"name": "ann  LEE"})  # e.g. imported or typed earlier
    assert not second_browser_attempt(group_sitting, pupils["ann"], "form")


def test_an_attempt_the_teacher_gave_to_someone_else_does_not_count(group_sitting, pupils):
    services.start_attempt(group_sitting, {"name": "Ann Lee"}, student=pupils["bob"])
    assert second_browser_attempt(group_sitting, pupils["ann"], "form")


def test_shared_computer_next_student_can_pick_their_own_name(client, group_sitting, pupils):
    pick(client, group_sitting, pupils["ann"])
    finish(client, group_sitting)
    r = client.get(f"/s/{group_sitting.code}/")  # same browser, previous student is done
    assert r.status_code == 200 and 'name="student"' in r.content.decode()
    assert pick(client, group_sitting, pupils["bob"]).status_code == 302
    assert group_sitting.attempts.filter(student=pupils["bob"]).count() == 1
    finish(client, group_sitting)
    # the first student again, in this browser: blocked by the per-student limit
    r = pick(client, group_sitting, pupils["ann"])
    assert r.status_code == 200 and "already taken" in r.content.decode()


def test_resuming_with_the_cookie_still_works(client, group_sitting, pupils):
    pick(client, group_sitting, pupils["ann"])
    r = client.get(f"/s/{group_sitting.code}/")
    assert r.status_code == 302 and r["Location"].endswith("/take/")


def test_free_name_sessions_keep_the_browser_limit(client, sitting):
    start(client, sitting)
    finish(client, sitting)
    assert client.get(f"/s/{sitting.code}/")["Location"].endswith("/done/")


# --- what the teacher sees ---------------------------------------------------------------------


def test_teacher_monitor_and_results_show_the_student_name(client, group_sitting, pupils, teacher):
    pick(client, group_sitting, pupils["ann"])
    teacher_client = Client()
    teacher_client.force_login(teacher)
    stats = teacher_client.get(reverse("delivery:stats", args=[group_sitting.pk])).json()
    assert stats["takers"][0]["name"] == "Ann Lee" and stats["takers"][0]["group"] == "7-A"
    assert stats["linked"] == 1 and stats["joined"] == 1
    page = teacher_client.get(reverse("delivery:share", args=[group_sitting.pk])).content.decode()
    assert "Ann Lee" in page and "(7-A)" in page and "1 of 1 linked" in page
    results = teacher_client.get(reverse("reports:session", args=[group_sitting.pk]))
    assert "Ann Lee" in results.content.decode()


def test_the_done_page_does_not_leak_other_students(client, group_sitting, pupils):
    pick(client, group_sitting, pupils["ann"])
    finish(client, group_sitting)
    html = client.get(f"/s/{group_sitting.code}/done/").content.decode()
    assert "Bob Ray" not in html and "ZEBRA-ACCEPT" not in html


def test_the_started_attempt_page_hides_the_roster(client, group_sitting, pupils):
    pick(client, group_sitting, pupils["ann"])
    html = client.get(f"/s/{group_sitting.code}/take/").content.decode()
    assert "Bob Ray" not in html and "Cleo Fox" not in html
    assert Student.objects.filter(pk=pupils["ann"].pk).exists()
