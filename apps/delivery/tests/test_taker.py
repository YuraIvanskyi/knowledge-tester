import json
import re
from datetime import timedelta

import pytest
from django.utils import timezone

from apps.delivery import services
from apps.delivery.models import Answer, Attempt, Sitting

from .conftest import start

pytestmark = pytest.mark.django_db


def attempt_of(sitting) -> Attempt:
    return sitting.attempts.get()


def save(client, sitting, answers):
    return client.post(
        f"/s/{sitting.code}/save/",
        data=json.dumps({"answers": answers}),
        content_type="application/json",
    )


def test_full_flow(client, sitting, grade_calls):
    # enter the code (lower case, stray spaces)
    r = client.post(
        "/s/enter/", {"code": f" {sitting.code.lower()[:3]} {sitting.code.lower()[3:]} "}
    )
    assert r.status_code == 302 and r["Location"] == f"/s/{sitting.code}/"

    page = client.get(f"/s/{sitting.code}/")
    assert page.status_code == 200
    html = page.content.decode()
    assert "7-A" in html and "Quick check." in html and "5 questions" in html and "10 min" in html
    assert 'name="tf_name"' in html

    r = start(client, sitting)
    assert r.status_code == 302 and r["Location"] == f"/s/{sitting.code}/take/"
    cookie = r.cookies[f"kt_attempt_{sitting.code}"]
    assert cookie["httponly"] and cookie["samesite"] == "Lax"
    attempt = attempt_of(sitting)
    assert cookie.value == str(attempt.token)
    assert attempt.taker == {"name": "Ann Lee", "class": ""}
    assert sorted(attempt.question_order) == ["q1", "q2", "q3", "q4", "q5"]
    assert attempt.deadline_at == attempt.started_at + timedelta(minutes=10)

    assert client.get(f"/s/{sitting.code}/take/").status_code == 200

    r = save(client, sitting, {"q1": ["a"], "q2": ["a", "b"], "q4": "ZEBRA-ACCEPT"})
    assert r.status_code == 200 and r.json()["answered"] == 3
    assert Answer.objects.get(attempt=attempt, question_key="q2").value == ["a", "b"]

    r = client.post(
        f"/s/{sitting.code}/submit/",
        {
            "form_sent": "1",
            "q_q1": "a",
            "q_q2": ["a", "b"],
            "q_q3": ["a", "b"],
            "q_q4": "ZEBRA-ACCEPT",
            "q_q5": "essay",
        },
    )
    assert r.status_code == 302 and r["Location"] == f"/s/{sitting.code}/done/"
    attempt.refresh_from_db()
    assert attempt.status == Attempt.Status.SUBMITTED and attempt.submitted_at
    assert grade_calls == [attempt.pk]
    assert attempt.max_score == 9
    assert attempt.score == 6  # open question (3) awaits review
    assert attempt.pending_reviews == 1

    done = client.get(f"/s/{sitting.code}/done/")
    html = done.content.decode()
    assert "Submitted" in html and "6 / 9" in html and "provisional" in html
    assert "ZEBRA-ACCEPT" not in html  # show_result=score hides correct answers

    # idempotent: repeat submit returns done and does not grade again
    r = client.post(f"/s/{sitting.code}/submit/", {"form_sent": "1", "q_q1": "b"})
    assert r["Location"] == f"/s/{sitting.code}/done/"
    assert grade_calls == [attempt.pk]
    assert Answer.objects.get(attempt=attempt, question_key="q1").value == ["a"]


def test_submit_without_js_fields_keeps_autosaved(client, sitting):
    start(client, sitting)
    save(client, sitting, {"q1": ["a"]})
    r = client.post(f"/s/{sitting.code}/submit/")
    assert r["Location"].endswith("/done/")
    assert Answer.objects.get(attempt=attempt_of(sitting), question_key="q1").value == ["a"]


def test_enter_unknown_code(client, sitting):
    r = client.post("/s/enter/", {"code": "ZZZZZZ"})
    assert r.status_code == 200
    html = r.content.decode()
    assert "ZZZZZZ" in html and 'name="code"' in html
    assert client.get("/s/ZZZZZZ/").status_code == 404
    assert client.get("/s/enter/").status_code == 302


def test_resume_via_cookie_keeps_order(client, sitting):
    start(client, sitting)
    save(client, sitting, {"q4": "half"})
    first = client.get(f"/s/{sitting.code}/take/").content.decode()
    again = client.get(f"/s/{sitting.code}/")
    assert again.status_code == 302 and again["Location"].endswith("/take/")
    second = client.get(f"/s/{sitting.code}/take/").content.decode()
    pattern = r'<fieldset class="question" id="(q-q\d)"'
    assert re.findall(pattern, first) == re.findall(pattern, second)
    assert len(re.findall(pattern, first)) == 5
    assert 'value="half"' in second
    assert sitting.attempts.count() == 1


def test_seeded_shuffle_is_stored_and_stable(client, sitting):
    start(client, sitting)
    attempt = attempt_of(sitting)
    order, options = services.shuffled_orders(sitting.revision.test, str(attempt.token))
    assert attempt.question_order == order
    assert attempt.option_orders == options
    assert sorted(options["q2"]) == ["a", "b", "c", "d"]
    assert "q4" not in options


def test_closed_session(client, sitting):
    sitting.status = Sitting.Status.CLOSED
    sitting.save()
    r = client.get(f"/s/{sitting.code}/")
    assert r.status_code == 200 and "closed" in r.content.decode().lower()
    assert 'name="tf_name"' not in r.content.decode()
    r = start(client, sitting)
    assert r.status_code == 200 and sitting.attempts.count() == 0


def test_required_question_message(client, sitting, grade_calls):
    start(client, sitting)
    r = client.post(f"/s/{sitting.code}/submit/", {"form_sent": "1", "q_q4": "x"})
    assert r.status_code == 200
    html = r.content.decode()
    assert "required questions" in html and 'href="#q-q1"' in html
    assert attempt_of(sitting).status == Attempt.Status.IN_PROGRESS
    assert not grade_calls
    assert 'value="x"' in html  # answers entered so far are kept
    r = client.post(f"/s/{sitting.code}/submit/", {"form_sent": "1", "q_q1": "b"})
    assert r["Location"].endswith("/done/")


def test_auto_submit_after_deadline_on_take(client, sitting, grade_calls):
    start(client, sitting)
    save(client, sitting, {"q1": ["a"]})
    attempt = attempt_of(sitting)
    Attempt.objects.filter(pk=attempt.pk).update(deadline_at=timezone.now() - timedelta(seconds=5))
    r = client.get(f"/s/{sitting.code}/take/")
    assert r.status_code == 302 and r["Location"].endswith("/done/")
    attempt.refresh_from_db()
    assert attempt.status == Attempt.Status.AUTO_SUBMITTED
    assert attempt.score == 1
    assert grade_calls == [attempt.pk]
    assert "automatically" in client.get(f"/s/{sitting.code}/done/").content.decode()


def test_autosave_after_deadline_finalizes(client, sitting):
    start(client, sitting)
    attempt = attempt_of(sitting)
    Attempt.objects.filter(pk=attempt.pk).update(deadline_at=timezone.now() - timedelta(minutes=5))
    r = save(client, sitting, {"q1": ["a"]})
    assert r.status_code == 409 and r.json()["done"] is True
    attempt.refresh_from_db()
    assert attempt.status == Attempt.Status.AUTO_SUBMITTED
    assert not Answer.objects.filter(
        attempt=attempt, question_key="q1", value__isnull=False
    ).exists()


def test_submit_just_after_deadline_is_accepted_as_auto_submitted(client, sitting):
    start(client, sitting)
    attempt = attempt_of(sitting)
    Attempt.objects.filter(pk=attempt.pk).update(deadline_at=timezone.now() - timedelta(seconds=2))
    r = client.post(f"/s/{sitting.code}/submit/", {"form_sent": "1", "q_q1": "a"})
    assert r["Location"].endswith("/done/")
    attempt.refresh_from_db()
    assert attempt.status == Attempt.Status.AUTO_SUBMITTED
    assert attempt.score == 1


def test_access_code(client, teacher, revision):
    sitting = services.create_sitting(
        revision=revision, user=teacher, title="t", access_code="Secret1"
    )
    assert "Access code" in client.get(f"/s/{sitting.code}/").content.decode()
    r = start(client, sitting, access_code="nope")
    assert r.status_code == 200 and "access code is not correct" in r.content.decode()
    assert sitting.attempts.count() == 0
    r = start(client, sitting, access_code=" secret1 ")
    assert r.status_code == 302 and sitting.attempts.count() == 1


def test_required_taker_field(client, sitting):
    r = client.post(f"/s/{sitting.code}/", {"tf_name": "  "})
    assert r.status_code == 200 and "Full name" in r.content.decode()
    assert sitting.attempts.count() == 0


def test_max_attempts_by_cookie_and_name(client, sitting):
    start(client, sitting, name="Ann  Lee")
    client.post(f"/s/{sitting.code}/submit/", {"form_sent": "1", "q_q1": "a"})
    # same browser: back to done
    assert client.get(f"/s/{sitting.code}/")["Location"].endswith("/done/")
    # other browser, same normalised name: blocked
    from django.test import Client

    other = Client()
    r = start(other, sitting, name="ann lee")
    assert r.status_code == 200 and "already taken" in r.content.decode()
    # different name: fine
    assert start(other, sitting, name="Bob").status_code == 302
    assert sitting.attempts.count() == 2


def test_max_attempts_two_allows_retry(client, make_sitting):
    sitting = make_sitting(max_attempts=2)
    start(client, sitting)
    client.post(f"/s/{sitting.code}/submit/", {"form_sent": "1", "q_q1": "a"})
    page = client.get(f"/s/{sitting.code}/")
    assert page.status_code == 200 and 'name="tf_name"' in page.content.decode()
    assert start(client, sitting).status_code == 302
    client.post(f"/s/{sitting.code}/submit/", {"form_sent": "1", "q_q1": "a"})
    r = start(client, sitting)
    assert r.status_code == 200 and "already taken" in r.content.decode()


def test_correct_answers_never_on_take_page(client, sitting):
    start(client, sitting)
    html = client.get(f"/s/{sitting.code}/take/").content.decode()
    low = html.lower()
    for secret in ("ZEBRA-ACCEPT", "SECRET-RUBRIC"):
        assert secret.lower() not in low
    assert "correct" not in low
    assert "weight" not in low
    assert 'type="radio"' in html and 'type="checkbox"' in html
    assert "Choose exactly 2" in html
    assert "<textarea" in html
    assert "style=" not in html and "<script>" not in html


def test_take_page_query_budget(client, sitting, django_assert_max_num_queries):
    start(client, sitting)
    save(client, sitting, {"q1": ["a"], "q4": "x"})
    with django_assert_max_num_queries(10):
        assert client.get(f"/s/{sitting.code}/take/").status_code == 200


def test_save_cleans_values(client, sitting):
    start(client, sitting)
    attempt = attempt_of(sitting)
    save(
        client,
        sitting,
        {"q1": ["a", "b"], "q2": ["zzz"], "q3": ["a", "b", "c", "d"], "q4": "  hi ", "nope": "x"},
    )
    values = {a.question_key: a.value for a in attempt.answers.all()}
    assert values == {"q1": ["a"], "q3": ["a", "b"], "q4": "hi"}  # server caps choose_n at n=2
    save(client, sitting, {"q4": ""})
    assert not Answer.objects.filter(attempt=attempt, question_key="q4").exists()
    assert save(client, sitting, "garbage").status_code == 400
    assert (
        client.post(
            f"/s/{sitting.code}/save/", data="{", content_type="application/json"
        ).status_code
        == 400
    )


def test_save_without_attempt(client, sitting):
    assert save(client, sitting, {"q1": ["a"]}).status_code == 403


@pytest.mark.parametrize("mode", ["none", "score", "full"])
def test_done_by_show_result(client, make_sitting, mode):
    sitting = make_sitting(show_result=mode)
    start(client, sitting)
    client.post(
        f"/s/{sitting.code}/submit/",
        {"form_sent": "1", "q_q1": "a", "q_q4": "wrong", "q_q5": "my essay"},
    )
    html = client.get(f"/s/{sitting.code}/done/").content.decode()
    assert "Submitted" in html
    if mode == "none":
        assert "Your result" not in html and "/ 9" not in html
    else:
        assert "Your result" in html and "1 / 9" in html
    if mode == "full":
        assert "ZEBRA-ACCEPT" in html and "one half" in html
        assert "Correct" in html and "Incorrect" in html and "Not answered" in html
        assert "my essay" in html
        assert "SECRET-RUBRIC" not in html
    else:
        assert "ZEBRA-ACCEPT" not in html


def test_done_without_attempt_redirects(client, sitting):
    assert client.get(f"/s/{sitting.code}/done/")["Location"] == f"/s/{sitting.code}/"
    assert client.get(f"/s/{sitting.code}/take/")["Location"] == f"/s/{sitting.code}/"
    assert client.post(f"/s/{sitting.code}/submit/")["Location"] == f"/s/{sitting.code}/"


def test_bad_cookie_is_ignored(client, sitting):
    client.cookies[f"kt_attempt_{sitting.code}"] = "not-a-uuid"
    assert client.get(f"/s/{sitting.code}/").status_code == 200
    assert client.get(f"/s/{sitting.code}/take/").status_code == 302


def test_lowercase_code_in_url(client, sitting):
    assert client.get(f"/s/{sitting.code.lower()}/").status_code == 200
