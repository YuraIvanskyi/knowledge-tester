"""Leaving the test page: services.record_away and the taker:away endpoint (the contract part)."""

import json

import pytest

from apps.delivery import services
from apps.delivery.models import Attempt

from .conftest import start

pytestmark = pytest.mark.django_db


def report(client, sitting, **payload):
    return client.post(
        f"/s/{sitting.code}/away/", data=json.dumps(payload), content_type="application/json"
    )


def test_record_away_adds_and_clamps(sitting):
    attempt = services.start_attempt(sitting, {"name": "Ann"})
    assert services.record_away(attempt, 1, 12)
    assert services.record_away(attempt, 2, 30)
    assert (attempt.away_count, attempt.away_seconds) == (3, 42)
    # a broken client cannot add more than the caps in one report, nor subtract
    services.record_away(attempt, 10_000, 10**9)
    assert attempt.away_count == 3 + services.AWAY_MAX_COUNT
    assert attempt.away_seconds == 42 + services.AWAY_MAX_SECONDS
    assert not services.record_away(attempt, -5, -5)
    assert not services.record_away(attempt, 0, 0)


def test_record_away_never_touches_a_finished_attempt(sitting):
    attempt = services.start_attempt(sitting, {"name": "Ann"})
    services.finalize(attempt)
    assert not services.record_away(attempt, 1, 5)
    attempt.refresh_from_db()
    assert (attempt.away_count, attempt.away_seconds) == (0, 0)


def test_endpoint_records_for_the_cookie_attempt(client, sitting):
    start(client, sitting)
    r = report(client, sitting, count=1, seconds=7)
    assert r.status_code == 200 and r.json() == {"recorded": True}
    attempt = sitting.attempts.get()
    assert (attempt.away_count, attempt.away_seconds) == (1, 7)


def test_endpoint_finds_the_attempt_by_page_token(client, sitting):
    attempt = services.start_attempt(sitting, {"name": "Ann"})
    r = report(client, sitting, attempt_token=str(attempt.token), count=2, seconds=3)
    assert r.json() == {"recorded": True}
    attempt.refresh_from_db()
    assert attempt.away_count == 2
    assert f"kt_attempt_{sitting.code}" not in r.cookies  # never sets a cookie


def test_endpoint_without_attempt_records_nothing(client, sitting):
    r = report(client, sitting, attempt_token="not-a-token", count=1, seconds=3)
    assert r.json() == {"recorded": False}
    assert not Attempt.objects.exists()  # never starts an attempt


def test_endpoint_after_submit_records_nothing(client, sitting):
    start(client, sitting)
    services.finalize(sitting.attempts.get())
    assert report(client, sitting, count=1, seconds=3).json() == {"recorded": False}


@pytest.mark.parametrize("body", [b"not json", b"[1, 2]"])
def test_endpoint_rejects_bad_bodies(client, sitting, body):
    r = client.post(f"/s/{sitting.code}/away/", data=body, content_type="application/json")
    assert r.status_code == 400


def test_endpoint_ignores_junk_numbers(client, sitting):
    start(client, sitting)
    r = report(client, sitting, count="many", seconds=None)
    assert r.json() == {"recorded": False}


def test_endpoint_is_post_only(client, sitting):
    assert client.get(f"/s/{sitting.code}/away/").status_code == 405
