"""PIN sessions: right and wrong PIN, no-PIN students, the retry limit."""

import hmac
import json
import re

import pytest
from django.test import Client

from apps.delivery import roster

from .conftest import pick

pytestmark = pytest.mark.django_db

WRONG = "0000"


def token_of(html: str) -> str:
    return re.search(r'name="attempt_token" value="([0-9a-f-]{36})"', html).group(1)


def try_path(sitting, student, pin, path="form", client=None):
    """One start attempt in a fresh browser through the given path. True if it started."""
    client = client or Client()
    data = {"student": str(student.pk), "pin": pin}
    token = token_of(client.get(f"/s/{sitting.code}/").content.decode())
    if path == "form":
        r = client.post(f"/s/{sitting.code}/", data)
        return r.status_code == 302, r
    if path == "autosave":
        body = {"answers": {"q1": ["a"]}, "unstarted": True, "attempt_token": token, **data}
        r = client.post(
            f"/s/{sitting.code}/save/", data=json.dumps(body), content_type="application/json"
        )
        return r.json()["started"], r
    r = client.post(
        f"/s/{sitting.code}/submit/",
        {"unstarted": "1", "attempt_token": token, "form_sent": "1", "q_q1": "a", **data},
    )
    return r.status_code == 302, r


def test_landing_page_asks_for_the_pin_and_never_shows_pins(client, pin_sitting, pupils):
    html = client.get(f"/s/{pin_sitting.code}/").content.decode()
    assert 'name="student"' in html and 'name="pin"' in html and 'type="password"' in html
    for pin in ("5829", "7314", "9065", "1357"):
        assert pin not in html
    assert "SECRET-NOTE" not in html


def test_a_student_without_a_pin_is_flagged_and_not_selectable(client, pin_sitting, pupils):
    html = client.get(f"/s/{pin_sitting.code}/").content.decode()
    cleo, ann = pupils["cleo"].pk, pupils["ann"].pk
    assert f'<option value="{cleo}" disabled>Cleo Fox (no PIN yet)</option>' in html
    assert f'<option value="{ann}">Ann Lee</option>' in html


def test_a_session_without_pins_does_not_flag_anyone(client, group_sitting, pupils):
    html = client.get(f"/s/{group_sitting.code}/").content.decode()
    assert "no PIN yet" not in html and "disabled" not in html


@pytest.mark.parametrize("path", ["form", "autosave", "submit"])
def test_right_pin_starts_the_attempt(pin_sitting, pupils, path):
    started, _response = try_path(pin_sitting, pupils["ann"], "5829", path)
    assert started
    attempt = pin_sitting.attempts.get()
    assert attempt.student == pupils["ann"] and attempt.taker["name"] == "Ann Lee"


@pytest.mark.parametrize("path", ["form", "autosave", "submit"])
def test_wrong_pin_is_refused_plainly(pin_sitting, pupils, path):
    started, response = try_path(pin_sitting, pupils["ann"], WRONG, path)
    assert not started and pin_sitting.attempts.count() == 0
    text = response.content.decode()
    assert "The PIN is not correct." in text
    assert "5829" not in text  # never echoed


@pytest.mark.parametrize("path", ["form", "autosave", "submit"])
def test_missing_pin_is_refused(pin_sitting, pupils, path):
    started, response = try_path(pin_sitting, pupils["ann"], "", path)
    assert not started and pin_sitting.attempts.count() == 0
    assert "Please type your PIN." in response.content.decode()


def test_another_students_pin_does_not_work(pin_sitting, pupils):
    assert not try_path(pin_sitting, pupils["ann"], "7314")[0]  # Bob's PIN for Ann
    assert pin_sitting.attempts.count() == 0


@pytest.mark.parametrize("path", ["form", "autosave", "submit"])
def test_a_student_without_a_pin_cannot_start(pin_sitting, pupils, path):
    for pin in ("", WRONG, "None"):
        started, response = try_path(pin_sitting, pupils["cleo"], pin, path)
        assert not started
    assert "no PIN yet" in response.content.decode()
    assert pin_sitting.attempts.count() == 0


def test_pin_is_ignored_in_a_session_without_pins(group_sitting, pupils):
    assert try_path(group_sitting, pupils["ann"], WRONG)[0]
    assert try_path(group_sitting, pupils["cleo"], "")[0]  # no PIN needed, none set


def test_spaces_and_case_in_the_pin_are_forgiven(teacher, pin_sitting, pupils):
    pupils["bob"].pin = "AB 12"
    pupils["bob"].save()
    assert try_path(pin_sitting, pupils["bob"], " ab12 ")[0]


def test_pin_is_compared_in_constant_time(pin_sitting, pupils, monkeypatch):
    calls = []
    real = hmac.compare_digest
    monkeypatch.setattr(
        roster.hmac, "compare_digest", lambda a, b: calls.append((a, b)) or real(a, b)
    )
    try_path(pin_sitting, pupils["ann"], "5829")
    assert calls == [(b"5829", b"5829")]


def test_page_rerendered_after_a_wrong_pin_keeps_the_pick_but_not_the_pin(pin_sitting, pupils):
    client = Client()
    token = token_of(client.get(f"/s/{pin_sitting.code}/").content.decode())
    r = client.post(
        f"/s/{pin_sitting.code}/submit/",
        {
            "unstarted": "1",
            "attempt_token": token,
            "form_sent": "1",
            "q_q4": "my-answer",
            "student": str(pupils["ann"].pk),
            "pin": WRONG,
        },
    )
    html = r.content.decode()
    assert f'<option value="{pupils["ann"].pk}" selected>' in html
    assert 'value="my-answer"' in html
    assert re.search(r'name="pin"[^>]*value=""', html) and WRONG not in html.replace(token, "")


# --- throttling --------------------------------------------------------------------------------


def test_too_many_wrong_pins_lock_the_student_for_a_while(pin_sitting, pupils):
    ann = pupils["ann"]
    for _ in range(roster.PIN_MAX_FAILURES):
        started, response = try_path(pin_sitting, ann, WRONG)
        assert not started and "The PIN is not correct." in response.content.decode()
    started, response = try_path(pin_sitting, ann, "5829")  # even the right PIN now
    assert not started and "Too many wrong PINs" in response.content.decode()
    assert pin_sitting.attempts.count() == 0
    # other students are not affected
    assert try_path(pin_sitting, pupils["bob"], "7314")[0]


def test_the_lock_ends_with_the_window(pin_sitting, pupils):
    from django.core.cache import cache

    for _ in range(roster.PIN_MAX_FAILURES):
        try_path(pin_sitting, pupils["ann"], WRONG)
    assert roster.pin_is_throttled(pupils["ann"])
    cache.clear()  # what the expiry of the window does
    assert try_path(pin_sitting, pupils["ann"], "5829")[0]


def test_failures_below_the_limit_are_forgotten_after_a_success(pin_sitting, pupils):
    for _ in range(roster.PIN_MAX_FAILURES - 1):
        try_path(pin_sitting, pupils["ann"], WRONG)
    assert try_path(pin_sitting, pupils["ann"], "5829")[0]
    pupils["ann"].refresh_from_db()
    assert not roster.pin_is_throttled(pupils["ann"])
    from django.core.cache import cache

    assert cache.get(f"kt:pin-fail:{pupils['ann'].pk}") is None


def test_the_counter_is_per_student_across_sessions(teacher, revision, group, pin_sitting, pupils):
    from apps.delivery import services

    second = services.create_sitting(
        revision=revision, user=teacher, title="again", group=group, use_pin=True
    )
    for _ in range(3):
        try_path(pin_sitting, pupils["ann"], WRONG)
    for _ in range(2):
        try_path(second, pupils["ann"], WRONG)
    assert not try_path(second, pupils["ann"], "5829")[0]  # locked through either session


def test_missing_pin_and_unknown_student_do_not_count_as_failures(pin_sitting, pupils):
    for _ in range(roster.PIN_MAX_FAILURES + 2):
        try_path(pin_sitting, pupils["ann"], "")
    assert not roster.pin_is_throttled(pupils["ann"])
    assert try_path(pin_sitting, pupils["ann"], "5829")[0]


def test_the_pin_is_not_checked_while_the_access_code_is_wrong(teacher, revision, group, pupils):
    from apps.delivery import services

    sitting = services.create_sitting(
        revision=revision,
        user=teacher,
        title="t",
        access_code="open-sesame",
        group=group,
        use_pin=True,
    )
    client = Client()
    r = client.post(
        f"/s/{sitting.code}/",
        {"student": pupils["ann"].pk, "pin": WRONG, "access_code": "nope"},
    )
    assert "access code is not correct" in r.content.decode()
    assert not roster.pin_is_throttled(pupils["ann"])
    assert (
        pick(client, sitting, pupils["ann"], pin="5829", access_code="open-sesame").status_code
        == 302
    )


def test_the_attempt_limit_is_only_revealed_after_the_right_pin(pin_sitting, pupils):
    assert try_path(pin_sitting, pupils["ann"], "5829")[0]
    started, response = try_path(pin_sitting, pupils["ann"], WRONG)
    assert "already taken" not in response.content.decode()
    started, response = try_path(pin_sitting, pupils["ann"], "5829")
    assert not started and "already taken" in response.content.decode()
