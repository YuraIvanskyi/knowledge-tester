"""Adding time for the students who are still working (teacher action on the session page)."""

import json
from datetime import timedelta
from pathlib import Path

import pytest
from django.contrib.messages import get_messages
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from apps.delivery import services
from apps.delivery.models import Attempt

from .conftest import start

pytestmark = pytest.mark.django_db


@pytest.fixture
def teacher_client(client, teacher):
    client.force_login(teacher)
    return client


def url(sitting):
    return reverse("delivery:extend", args=[sitting.pk])


def test_everyone_still_working_gets_the_minutes(sitting):
    start(Client(), sitting, "Ann")
    start(Client(), sitting, "Bob")
    before = {a.pk: a.deadline_at for a in sitting.attempts.all()}
    assert services.extend_time(sitting, 5) == 2
    for attempt in sitting.attempts.all():
        assert attempt.deadline_at == before[attempt.pk] + timedelta(minutes=5)


def test_an_attempt_that_just_ran_out_counts_from_now(sitting):
    start(Client(), sitting, "Ann")
    attempt = sitting.attempts.get()
    attempt.deadline_at = timezone.now() - timedelta(seconds=20)
    attempt.save()
    assert services.extend_time(sitting, 5) == 1
    attempt.refresh_from_db()
    left = attempt.deadline_at - timezone.now()
    assert timedelta(minutes=4, seconds=50) < left <= timedelta(minutes=5)
    assert not services.enforce_deadline(attempt)


def test_finished_and_untimed_attempts_are_not_touched(sitting, make_sitting):
    start(Client(), sitting, "Ann")
    finished = sitting.attempts.get()
    services.finalize(finished)
    deadline = finished.deadline_at
    assert services.extend_time(sitting, 10) == 0
    finished.refresh_from_db()
    assert finished.deadline_at == deadline and finished.status == Attempt.Status.SUBMITTED

    untimed = make_sitting(time_limit_minutes=None)
    start(Client(), untimed, "Bob")
    assert services.extend_time(untimed, 10) == 0
    assert untimed.attempts.get().deadline_at is None


def test_zero_or_negative_minutes_do_nothing(sitting):
    start(Client(), sitting, "Ann")
    deadline = sitting.attempts.get().deadline_at
    assert services.extend_time(sitting, 0) == 0
    assert services.extend_time(sitting, -5) == 0
    assert sitting.attempts.get().deadline_at == deadline


def test_teacher_adds_time_from_the_session_page(teacher_client, sitting):
    start(Client(), sitting, "Ann")
    deadline = sitting.attempts.get().deadline_at
    html = teacher_client.get(reverse("delivery:share", args=[sitting.pk])).content.decode()
    assert f'action="{url(sitting)}"' in html
    for minutes in services.EXTEND_CHOICES:
        assert f'name="minutes" value="{minutes}"' in html

    response = teacher_client.post(url(sitting), {"minutes": "10"})
    assert response["Location"] == reverse("delivery:share", args=[sitting.pk])
    assert sitting.attempts.get().deadline_at == deadline + timedelta(minutes=10)
    message = [str(m) for m in get_messages(response.wsgi_request)]
    assert message[0].startswith("10 more minutes for 1 student who is still working.")


def test_nobody_working_is_said_plainly(teacher_client, sitting):
    response = teacher_client.post(url(sitting), {"minutes": "5"})
    assert [str(m) for m in get_messages(response.wsgi_request)] == [
        "Nobody is working against the clock right now."
    ]


@pytest.mark.parametrize("minutes", ["", "0", "7", "-5", "999", "5.5", "abc", "٥", "5" * 40])
def test_only_the_offered_steps_are_accepted(teacher_client, sitting, minutes):
    start(Client(), sitting, "Ann")
    deadline = sitting.attempts.get().deadline_at
    response = teacher_client.post(url(sitting), {"minutes": minutes})
    assert response.status_code == 302
    assert sitting.attempts.get().deadline_at == deadline


def test_extend_is_post_only_and_404_for_others(client, other_teacher, teacher_client, sitting):
    start(Client(), sitting, "Ann")
    deadline = sitting.attempts.get().deadline_at
    assert teacher_client.get(url(sitting)).status_code == 405
    stranger = Client()
    stranger.force_login(other_teacher)
    assert stranger.post(url(sitting), {"minutes": "5"}).status_code == 404
    anonymous = Client().post(url(sitting), {"minutes": "5"})
    assert anonymous.status_code == 302 and "/accounts/login/" in anonymous["Location"]
    assert sitting.attempts.get().deadline_at == deadline


def test_a_closed_session_gets_no_time(teacher_client, sitting):
    start(Client(), sitting, "Ann")
    services.close_sitting(sitting)
    response = teacher_client.post(url(sitting), {"minutes": "5"})
    assert [str(m) for m in get_messages(response.wsgi_request)] == [
        "Time can only be added while the session is open."
    ]
    html = teacher_client.get(reverse("delivery:share", args=[sitting.pk])).content.decode()
    assert url(sitting) not in html


def test_untimed_tests_show_no_add_time_buttons(teacher_client, make_sitting):
    untimed = make_sitting(time_limit_minutes=None)
    html = teacher_client.get(reverse("delivery:share", args=[untimed.pk])).content.decode()
    assert url(untimed) not in html


def test_the_students_page_learns_the_new_time_from_an_empty_save(sitting):
    """timer.js polls the autosave endpoint without answers; the reply carries the time left."""
    student = Client()
    start(student, sitting, "Ann")
    save_url = f"/s/{sitting.code}/save/"

    def left():
        response = student.post(
            save_url, json.dumps({"answers": {}}), content_type="application/json"
        )
        assert response.status_code == 200
        return response.json()["left"]

    before = left()
    services.extend_time(sitting, 5)
    assert 295 <= left() - before <= 300
    assert sitting.attempts.get().answers.count() == 0  # the poll saved nothing


def test_the_poll_sends_a_finished_student_to_the_done_page(sitting):
    student = Client()
    start(student, sitting, "Ann")
    services.close_sitting(sitting)
    response = student.post(
        f"/s/{sitting.code}/save/", json.dumps({"answers": {}}), content_type="application/json"
    )
    assert response.status_code == 409
    assert response.json()["url"] == f"/s/{sitting.code}/done/"


def test_timer_script_follows_the_server():
    js = (Path(__file__).resolve().parents[3] / "static" / "js" / "timer.js").read_text(
        encoding="utf-8"
    )
    # asks the server (an empty autosave) regularly and before the automatic submit
    assert "data-save-url" in js and "answers: {}" in js
    assert "sync(true)" in js and "sync(false)" in js
    # a second call moves the deadline instead of being ignored
    assert "end = fresh" in js
