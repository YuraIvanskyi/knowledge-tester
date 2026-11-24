"""The timer's submit at 0 that arrives a moment early, the clock without JavaScript, and
departures counted by a submit that starts the attempt."""

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.delivery import services
from apps.delivery.models import Attempt

from .conftest import start

pytestmark = pytest.mark.django_db


def deadline_in(attempt, seconds):
    Attempt.objects.filter(pk=attempt.pk).update(
        deadline_at=timezone.now() + timedelta(seconds=seconds)
    )


def submit(client, sitting, **data):
    return client.post(f"/s/{sitting.code}/submit/", {"form_sent": "1", **data})


def test_timer_submit_a_moment_early_is_automatic(client, sitting):
    start(client, sitting)
    attempt = sitting.attempts.get()
    deadline_in(attempt, 3)  # the phone's clock ran a little ahead
    # q1 is required and empty: the automatic submit must not stop at the "required" panel
    r = submit(client, sitting, confirm_unanswered="1", timer_expired="1")
    assert r.status_code == 302 and r["Location"] == f"/s/{sitting.code}/done/"
    attempt.refresh_from_db()
    assert attempt.status == Attempt.Status.AUTO_SUBMITTED


def test_timer_flag_long_before_the_deadline_is_a_normal_submit(client, sitting):
    start(client, sitting)
    attempt = sitting.attempts.get()
    deadline_in(attempt, 60)  # not the timer: a tampered or stale page
    r = submit(client, sitting, confirm_unanswered="1", timer_expired="1")
    assert r.status_code == 200 and "Please answer these required questions" in r.content.decode()
    attempt.refresh_from_db()
    assert attempt.status == Attempt.Status.IN_PROGRESS


def test_without_the_flag_a_submit_near_the_deadline_still_asks(client, sitting):
    start(client, sitting)
    attempt = sitting.attempts.get()
    deadline_in(attempt, 3)
    r = submit(client, sitting, q_q1="a")
    assert r.status_code == 200 and 'id="unanswered"' in r.content.decode()
    r = submit(client, sitting, q_q1="a", confirm_unanswered="1")
    attempt.refresh_from_db()
    assert attempt.status == Attempt.Status.SUBMITTED


def test_timer_shows_minutes_and_seconds_without_javascript(client, sitting):
    start(client, sitting)
    deadline_in(sitting.attempts.get(), 9 * 60 + 5)
    html = client.get(f"/s/{sitting.code}/take/").content.decode()
    assert ">9:0" in html  # 9:05 or 9:04 by the time the page renders
    assert 'data-seconds-left="54' in html


def test_clock_format():
    assert services.clock(0) == "0:00"
    assert services.clock(9) == "0:09"
    assert services.clock(605) == "10:05"
    assert services.clock(3720) == "1:02:00"
    assert services.clock(None) == "0:00"


def test_submit_that_starts_the_attempt_counts_earlier_departures(client, sitting):
    page = client.get(f"/s/{sitting.code}/")
    token = page.context["token"]
    r = submit(
        client,
        sitting,
        unstarted="1",
        attempt_token=str(token),
        tf_name="Ann Lee",
        q_q1="a",
        confirm_unanswered="1",
        away_count="2",
        away_seconds="41",
    )
    assert r.status_code == 302
    attempt = sitting.attempts.get()
    assert attempt.status == Attempt.Status.SUBMITTED
    assert (attempt.away_count, attempt.away_seconds) == (2, 41)


def test_submit_of_an_existing_attempt_ignores_the_fields(client, sitting):
    # The page reported those departures itself already: counting them again would double them.
    start(client, sitting)
    attempt = sitting.attempts.get()
    services.record_away(attempt, 1, 10)
    submit(client, sitting, q_q1="a", confirm_unanswered="1", away_count="1", away_seconds="10")
    attempt.refresh_from_db()
    assert (attempt.away_count, attempt.away_seconds) == (1, 10)
