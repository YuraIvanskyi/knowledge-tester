"""Two requests for the same attempt arriving together (a busy LAN, a double tap, a slow phone)."""

import json
import uuid

import pytest
from django.test import Client

from apps.delivery import services
from apps.delivery.models import Attempt

pytestmark = pytest.mark.django_db


def autosave(client, sitting, token, answers):
    payload = {"unstarted": True, "attempt_token": token, "tf_name": "Ann Lee", "answers": answers}
    return client.post(
        f"/s/{sitting.code}/save/", data=json.dumps(payload), content_type="application/json"
    )


@pytest.mark.parametrize("max_attempts", [1, 3])
def test_a_second_autosave_before_the_cookie_arrived_joins_the_same_attempt(
    make_sitting, max_attempts
):
    sitting = make_sitting(max_attempts=max_attempts)
    token = str(uuid.uuid4())
    first = autosave(Client(), sitting, token, {"q1": ["a"]})
    assert first.status_code == 200 and first.json()["started"] is True
    # the same page, a second request without the cookie the first response was about to set
    second = autosave(Client(), sitting, token, {"q1": ["a"], "q4": "0.75"})
    assert second.status_code == 200, second.content
    assert second.json().get("started") is True
    assert Attempt.objects.filter(sitting=sitting).count() == 1
    assert second.cookies, "the cookie is set again, so the browser ends up with the attempt"


def test_start_attempt_is_idempotent_for_a_token(make_sitting):
    sitting = make_sitting()
    token = uuid.uuid4()
    one = services.start_attempt(sitting, {"name": "Ann"}, token=token)
    two = services.start_attempt(sitting, {"name": "Ann"}, token=token)
    assert one.pk == two.pk and Attempt.objects.count() == 1


def test_a_token_of_another_session_is_not_reused(make_sitting):
    first, second = make_sitting(), make_sitting()
    token = uuid.uuid4()
    one = services.start_attempt(first, {"name": "Ann"}, token=token)
    two = services.start_attempt(second, {"name": "Ann"}, token=token)
    assert one.pk != two.pk and two.token != token and two.sitting_id == second.pk


def test_the_loser_of_a_finalize_race_sees_a_graded_attempt(make_sitting):
    sitting = make_sitting()
    attempt = services.start_attempt(sitting, {"name": "Ann"})
    services.save_answers(attempt, sitting.revision.test, {"q1": ["a"]})
    stale = Attempt.objects.get(pk=attempt.pk)  # what the second request loaded before the flip
    assert services.finalize(attempt) is True
    assert services.finalize(stale) is False
    assert stale.status == Attempt.Status.SUBMITTED
    assert stale.score is not None  # refreshed from a committed, graded row
