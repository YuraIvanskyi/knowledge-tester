"""The session URL (the QR target) shows the test itself, not a join screen (untimed tests)."""

import json
import re

import pytest

from apps.delivery.models import Attempt

pytestmark = pytest.mark.django_db


@pytest.fixture
def untimed(make_sitting):
    return make_sitting(time_limit_minutes=None)


def token_of(html: str) -> str:
    return re.search(r'name="attempt_token" value="([0-9a-f-]{36})"', html).group(1)


def test_session_url_shows_the_test_not_a_join_screen(client, untimed):
    r = client.get(f"/s/{untimed.code}/")
    html = r.content.decode()
    assert r.status_code == 200
    assert 'name="tf_name"' in html  # identity fields live on the test page
    assert 'name="q_q1"' in html  # the questions are right there
    assert ">Start<" not in html
    assert not Attempt.objects.exists()  # opening the link creates nothing


def test_timed_test_also_opens_directly_and_the_clock_starts_on_first_save(client, sitting):
    html = client.get(f"/s/{sitting.code}/").content.decode()
    assert 'name="q_q1"' in html and ">Start<" not in html
    assert "The clock starts when you begin answering" in html
    assert not Attempt.objects.exists()
    r = save_unstarted(client, sitting, token_of(html), {"q1": ["a"]}, tf_name="Ann Lee")
    assert r.json()["started"] is True and 0 < r.json()["left"] <= 600
    assert sitting.attempts.get().deadline_at is not None


def test_submit_creates_attempt_with_the_shown_token(client, untimed, grade_calls):
    token = token_of(client.get(f"/s/{untimed.code}/").content.decode())
    r = client.post(
        f"/s/{untimed.code}/submit/",
        {
            "unstarted": "1",
            "attempt_token": token,
            "form_sent": "1",
            "confirm_unanswered": "1",
            "tf_name": "Ann Lee",
            "q_q1": ["a"],
        },
    )
    assert r["Location"] == f"/s/{untimed.code}/done/"
    attempt = untimed.attempts.get()
    assert str(attempt.token) == token and attempt.taker["name"] == "Ann Lee"
    assert attempt.status == Attempt.Status.SUBMITTED and grade_calls
    assert f"kt_attempt_{untimed.code}" in r.cookies
    assert client.get(f"/s/{untimed.code}/done/").status_code == 200


def test_double_submit_is_idempotent(client, untimed):
    token = token_of(client.get(f"/s/{untimed.code}/").content.decode())
    data = {
        "unstarted": "1",
        "attempt_token": token,
        "form_sent": "1",
        "confirm_unanswered": "1",
        "tf_name": "Ann Lee",
    }
    data["q_q1"] = "a"
    first = client.post(f"/s/{untimed.code}/submit/", data)
    second = client.post(f"/s/{untimed.code}/submit/", data)
    assert first["Location"] == second["Location"] == f"/s/{untimed.code}/done/"
    assert untimed.attempts.count() == 1


def test_missing_name_rerenders_with_answers_and_creates_nothing(client, untimed):
    token = token_of(client.get(f"/s/{untimed.code}/").content.decode())
    r = client.post(
        f"/s/{untimed.code}/submit/",
        {
            "unstarted": "1",
            "attempt_token": token,
            "form_sent": "1",
            "confirm_unanswered": "1",
            "tf_name": " ",
            "q_q1": "a",
        },
    )
    html = r.content.decode()
    assert r.status_code == 200 and "Please fill in" in html
    assert token_of(html) == token  # same shuffle after the error
    assert re.search(r'name="q_q1"[^>]*value="a"[^>]*checked', html)  # answer kept
    assert not Attempt.objects.exists()


def save_unstarted(client, sitting, token, answers, **fields):
    body = {"answers": answers, "unstarted": True, "attempt_token": token, **fields}
    return client.post(
        f"/s/{sitting.code}/save/", data=json.dumps(body), content_type="application/json"
    )


def test_autosave_starts_the_attempt_once_details_are_valid(client, untimed):
    token = token_of(client.get(f"/s/{untimed.code}/").content.decode())
    r = save_unstarted(client, untimed, token, {"q1": ["a"]}, tf_name="")
    assert r.json()["started"] is False and not Attempt.objects.exists()

    r = save_unstarted(client, untimed, token, {"q1": ["a"]}, tf_name="Ann Lee")
    assert r.json()["started"] is True and f"kt_attempt_{untimed.code}" in r.cookies
    attempt = untimed.attempts.get()
    assert str(attempt.token) == token
    assert attempt.answers.get(question_key="q1").value == ["a"]

    done = client.post(
        f"/s/{untimed.code}/submit/",
        {"unstarted": "1", "attempt_token": token, "tf_name": "Ann Lee", "confirm_unanswered": "1"},
    )
    assert done["Location"] == f"/s/{untimed.code}/done/"
    assert untimed.attempts.count() == 1


def test_reopening_the_link_resumes_the_attempt(client, untimed):
    token = token_of(client.get(f"/s/{untimed.code}/").content.decode())
    save_unstarted(client, untimed, token, {"q1": ["a"]}, tf_name="Ann Lee")
    r = client.get(f"/s/{untimed.code}/")
    assert r["Location"] == f"/s/{untimed.code}/take/"


def test_closed_session_refuses_direct_start(client, untimed):
    token = token_of(client.get(f"/s/{untimed.code}/").content.decode())
    from apps.delivery import services

    services.close_sitting(untimed)
    r = save_unstarted(client, untimed, token, {"q1": ["a"]}, tf_name="Ann Lee")
    assert r.status_code == 403
    r = client.post(
        f"/s/{untimed.code}/submit/",
        {"unstarted": "1", "attempt_token": token, "tf_name": "Ann Lee"},
    )
    assert r.status_code == 302 and not Attempt.objects.exists()


def test_access_code_required_on_direct_page(client, untimed):
    untimed.access_code = "open-sesame"
    untimed.save()
    html = client.get(f"/s/{untimed.code}/").content.decode()
    assert 'name="access_code"' in html
    token = token_of(html)
    data = {
        "unstarted": "1",
        "attempt_token": token,
        "form_sent": "1",
        "confirm_unanswered": "1",
        "tf_name": "Ann",
    }
    data["q_q1"] = "a"
    r = client.post(f"/s/{untimed.code}/submit/", {**data, "access_code": "nope"})
    assert "access code is not correct" in r.content.decode()
    assert not Attempt.objects.exists()
    r = client.post(f"/s/{untimed.code}/submit/", {**data, "access_code": "OPEN-sesame"})
    assert r["Location"] == f"/s/{untimed.code}/done/"
