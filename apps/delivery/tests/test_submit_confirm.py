"""UX-01 (taker part): ask once before submitting unanswered questions; a cancelled (voided)
attempt never blocks a new one. UX-10: a class session does not ask for the class."""

import json
import re
from datetime import timedelta
from pathlib import Path

import pytest
from django.conf import settings
from django.test import Client
from django.utils import timezone

from apps.delivery import services
from apps.delivery.models import Attempt, Sitting

from .conftest import make_document, make_revision, pick, start

pytestmark = pytest.mark.django_db

ALL_ANSWERS = {
    "form_sent": "1",
    "q_q1": "a",
    "q_q2": ["a", "b"],
    "q_q3": ["a", "b"],
    "q_q4": "ZEBRA-ACCEPT",
    "q_q5": "essay",
}


def post_submit(client, sitting, data=None):
    return client.post(f"/s/{sitting.code}/submit/", data or {})


def the_attempt(sitting) -> Attempt:
    return sitting.attempts.get()


# --- the confirmation panel --------------------------------------------------------------------


@pytest.fixture
def optional_sitting(teacher):
    doc = make_document()
    doc["test"]["questions"][0]["required"] = False
    return services.create_sitting(revision=make_revision(teacher, doc), user=teacher, title="O")


def test_empty_submit_shows_the_panel_and_does_not_finish(client, optional_sitting):
    sitting = optional_sitting
    start(client, sitting)
    r = post_submit(client, sitting, {"form_sent": "1"})
    html = r.content.decode()
    assert r.status_code == 200
    assert 'id="unanswered"' in html and 'name="confirm_unanswered"' in html
    assert "You have answered 0 of 5 questions." in html
    assert the_attempt(sitting).status == Attempt.Status.IN_PROGRESS


def test_partial_submit_counts_and_links_the_unanswered_questions(client, sitting):
    start(client, sitting)
    r = post_submit(client, sitting, {"form_sent": "1", "q_q1": "a", "q_q4": "x"})
    html = r.content.decode()
    assert "You have answered 2 of 5 questions." in html
    links = re.findall(r'href="#q-(\w+)"', html)
    assert sorted(links) == ["q2", "q3", "q5"]
    assert the_attempt(sitting).status == Attempt.Status.IN_PROGRESS
    # the answers that were posted are kept on the page and saved
    assert re.search(r'name="q_q4"[^>]*value="x"', html)
    assert the_attempt(sitting).answers.get(question_key="q4").value == "x"


def test_confirmed_submit_finishes(client, sitting):
    start(client, sitting)
    post_submit(client, sitting, {"form_sent": "1", "q_q1": "a"})
    r = post_submit(client, sitting, {"form_sent": "1", "q_q1": "a", "confirm_unanswered": "1"})
    assert r["Location"] == f"/s/{sitting.code}/done/"
    assert the_attempt(sitting).status == Attempt.Status.SUBMITTED


def test_fully_answered_form_finishes_in_one_post(client, sitting):
    start(client, sitting)
    r = post_submit(client, sitting, ALL_ANSWERS)
    assert r["Location"] == f"/s/{sitting.code}/done/"
    assert the_attempt(sitting).status == Attempt.Status.SUBMITTED


def test_required_questions_still_come_first(client, sitting):
    start(client, sitting)  # q1 is required
    r = post_submit(client, sitting, {"form_sent": "1", "confirm_unanswered": "1"})
    html = r.content.decode()
    assert 'id="missing"' in html and 'id="unanswered"' not in html
    assert the_attempt(sitting).status == Attempt.Status.IN_PROGRESS


def test_past_the_deadline_any_submit_finishes_without_asking(client, sitting):
    start(client, sitting)
    attempt = the_attempt(sitting)
    attempt.deadline_at = timezone.now() - timedelta(minutes=1)
    attempt.save()
    r = post_submit(client, sitting, {"form_sent": "1"})
    assert r["Location"] == f"/s/{sitting.code}/done/"
    attempt.refresh_from_db()
    assert attempt.status == Attempt.Status.AUTO_SUBMITTED


def test_timer_script_adds_the_confirmation_flag_before_its_automatic_submit():
    source = (Path(settings.BASE_DIR) / "static" / "js" / "timer.js").read_text(encoding="utf-8")
    assert source.index("confirm_unanswered") < source.index("form.submit()")


def test_first_submit_of_the_unstarted_page_creates_the_attempt_and_asks(untimed_sitting):
    client = Client()
    html = client.get(f"/s/{untimed_sitting.code}/").content.decode()
    token = re.search(r'name="attempt_token" value="([0-9a-f-]{36})"', html).group(1)
    data = {
        "unstarted": "1",
        "attempt_token": token,
        "form_sent": "1",
        "tf_name": "Ann Lee",
        "q_q1": "a",
    }
    r = client.post(f"/s/{untimed_sitting.code}/submit/", data)
    assert r.status_code == 200 and 'id="unanswered"' in r.content.decode()
    assert f"kt_attempt_{untimed_sitting.code}" in r.cookies  # the attempt exists now
    attempt = the_attempt(untimed_sitting)
    assert str(attempt.token) == token and attempt.status == Attempt.Status.IN_PROGRESS

    again = client.post(f"/s/{untimed_sitting.code}/submit/", {**data, "confirm_unanswered": "1"})
    assert again["Location"] == f"/s/{untimed_sitting.code}/done/"
    assert untimed_sitting.attempts.count() == 1


@pytest.fixture
def untimed_sitting(teacher):
    revision = make_revision(teacher, make_document(time_limit_minutes=None))
    return services.create_sitting(revision=revision, user=teacher, title="S")


def test_panel_is_not_shown_on_a_plain_take_page(client, sitting):
    start(client, sitting)
    html = client.get(f"/s/{sitting.code}/take/").content.decode()
    assert 'id="unanswered"' not in html
    assert 'id="save-status"' in html and 'data-warn="1 minute left"' in html


# --- cancelled attempts ------------------------------------------------------------------------


def test_take_with_a_voided_attempt_redirects_to_done(client, sitting):
    start(client, sitting)
    services.void_attempt(the_attempt(sitting))
    assert client.get(f"/s/{sitting.code}/take/")["Location"] == f"/s/{sitting.code}/done/"


def test_voided_attempt_lets_the_same_browser_start_again(client, sitting):
    start(client, sitting)
    services.void_attempt(the_attempt(sitting))

    page = client.get(f"/s/{sitting.code}/")
    html = page.content.decode()
    assert page.status_code == 200 and 'name="tf_name"' in html
    assert "cancelled your previous attempt" in html

    r = start(client, sitting)  # same cookie, same name, max_attempts = 1
    assert r["Location"] == f"/s/{sitting.code}/take/"
    assert sitting.attempts.count() == 2
    assert sitting.attempts.exclude(status=Attempt.Status.VOIDED).get().status == (
        Attempt.Status.IN_PROGRESS
    )


def test_voided_attempt_then_a_direct_submit_starts_a_new_one(client, untimed_sitting):
    first = Client()
    html = first.get(f"/s/{untimed_sitting.code}/").content.decode()
    token = re.search(r'name="attempt_token" value="([0-9a-f-]{36})"', html).group(1)
    first.post(
        f"/s/{untimed_sitting.code}/save/",
        data=json.dumps(
            {"answers": {"q1": ["a"]}, "unstarted": True, "attempt_token": token, "tf_name": "Ann"}
        ),
        content_type="application/json",
    )
    services.void_attempt(the_attempt(untimed_sitting))

    html = first.get(f"/s/{untimed_sitting.code}/").content.decode()
    new_token = re.search(r'name="attempt_token" value="([0-9a-f-]{36})"', html).group(1)
    r = first.post(
        f"/s/{untimed_sitting.code}/submit/",
        {
            "unstarted": "1",
            "attempt_token": new_token,
            "form_sent": "1",
            "confirm_unanswered": "1",
            "tf_name": "Ann",
            "q_q1": "a",
        },
    )
    assert r["Location"] == f"/s/{untimed_sitting.code}/done/"
    assert untimed_sitting.attempts.count() == 2


def test_done_page_of_a_voided_attempt_offers_a_new_try_while_the_session_is_open(client, sitting):
    start(client, sitting)
    services.void_attempt(the_attempt(sitting))
    html = client.get(f"/s/{sitting.code}/done/").content.decode()
    assert "Attempt cancelled" in html and "Take the test again" in html

    services.close_sitting(sitting)
    html = client.get(f"/s/{sitting.code}/done/").content.decode()
    assert "Attempt cancelled" in html and "Take the test again" not in html


def test_closed_session_still_sends_a_voided_attempt_to_done(client, sitting):
    start(client, sitting)
    services.void_attempt(the_attempt(sitting))
    services.close_sitting(sitting)
    assert client.get(f"/s/{sitting.code}/")["Location"] == f"/s/{sitting.code}/done/"
    assert Sitting.objects.get(pk=sitting.pk).status == Sitting.Status.CLOSED


def test_class_session_voided_attempt_lets_the_student_start_again(client, group_sitting, pupils):
    pick(client, group_sitting, pupils["ann"])
    services.void_attempt(group_sitting.attempts.get())
    html = client.get(f"/s/{group_sitting.code}/").content.decode()
    assert "cancelled your previous attempt" in html and 'name="student"' in html
    r = pick(client, group_sitting, pupils["ann"])
    assert r["Location"] == f"/s/{group_sitting.code}/take/"
    assert group_sitting.attempts.filter(student=pupils["ann"]).count() == 2


# --- UX-10: class sessions ---------------------------------------------------------------------


def test_class_session_does_not_ask_for_the_class_and_stores_the_group_name(
    client, group_sitting, pupils
):
    html = client.get(f"/s/{group_sitting.code}/").content.decode()
    assert 'name="student"' in html
    assert 'name="tf_class"' not in html and 'name="tf_name"' not in html

    r = pick(client, group_sitting, pupils["ann"], tf_class="typed")
    assert r["Location"] == f"/s/{group_sitting.code}/take/"
    assert group_sitting.attempts.get().taker == {"name": "Ann Lee", "class": "7-A"}


def test_required_class_field_does_not_block_a_class_session(teacher, group, pupils, client):
    doc = make_document()
    doc["test"]["taker_fields"][1]["required"] = True
    sitting = services.create_sitting(
        revision=make_revision(teacher, doc), user=teacher, title="S", group=group
    )
    assert pick(client, sitting, pupils["ann"])["Location"] == f"/s/{sitting.code}/take/"
    assert sitting.attempts.get().taker["class"] == "7-A"


def test_free_name_session_still_asks_the_class(client, sitting):
    html = client.get(f"/s/{sitting.code}/").content.decode()
    assert 'name="tf_class"' in html and 'name="tf_name"' in html


def test_pin_field_hints_a_numeric_keyboard(client, pin_sitting, pupils):
    html = client.get(f"/s/{pin_sitting.code}/").content.decode()
    pin = re.search(r'<input[^>]*name="pin"[^>]*>', html).group(0)
    assert 'inputmode="numeric"' in pin and 'pattern="[0-9]*"' in pin and 'maxlength="8"' in pin
