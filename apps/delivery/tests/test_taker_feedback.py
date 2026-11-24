"""Classroom feedback wave, student page (idea/specs/feedback-wave-contracts.md): Submit at the end
of the form (F-01), the confirm next to it and the "who is answering" line (F-02), the question
navigator (F-03), the page side of leaving-the-page tracking (F-04), one question per page (F-08)
and "another student on this device" (F-10)."""

import re
from pathlib import Path

import pytest
from django.conf import settings
from django.test import Client
from django.urls import reverse

from apps.delivery import services
from apps.delivery.models import Attempt

from .conftest import make_document, make_revision, pick, start

pytestmark = pytest.mark.django_db

STATIC = Path(settings.BASE_DIR) / "static"


def take_page(client, sitting) -> str:
    start(client, sitting, tf_class="7-B")
    return client.get(f"/s/{sitting.code}/take/").content.decode()


def sticky_bar(html: str) -> str:
    return re.search(r'<div class="sticky-bar">.*?</form>', html, re.S).group(0)


def submit_buttons(html: str) -> list[str]:
    return re.findall(r'<button[^>]*type="submit"[^>]*>', html)


# --- F-01: Submit is not in the bottom bar -----------------------------------------------------


@pytest.mark.parametrize("unstarted", [True, False])
def test_submit_sits_after_the_questions_not_in_the_bar(client, sitting, unstarted):
    html = (
        client.get(f"/s/{sitting.code}/").content.decode()
        if unstarted
        else take_page(client, sitting)
    )
    bar = sticky_bar(html)
    assert "<button" not in bar and 'id="answered-count"' in bar and 'id="save-status"' in bar
    assert 'id="timer"' in bar
    main = html.index('id="submit-main"')
    assert main > html.rindex('<fieldset class="question"') and main < html.index("sticky-bar")


def test_enter_in_a_text_field_never_submits(client, sitting):
    # The first submit button of the form is the default for Enter; it is a disabled guard.
    html = take_page(client, sitting)
    form = html[html.index('id="take-form"') :]
    first = submit_buttons(form)[0]
    assert "enter-guard" in first and "disabled" in first and "hidden" in first


# --- F-02: the confirm sits next to Submit; the name stays visible ------------------------------


def test_unanswered_panel_is_rendered_right_above_submit(client, sitting):
    start(client, sitting)
    html = client.post(
        f"/s/{sitting.code}/submit/", {"form_sent": "1", "q_q1": "a", "q_q4": "x"}
    ).content.decode()
    panel = html.index('id="unanswered"')
    assert html.rindex('<fieldset class="question"') < panel < html.index('id="submit-main"')
    assert "autofocus" in re.search(r'<div[^>]*id="unanswered"[^>]*>', html).group(0)
    assert sitting.attempts.get().status == Attempt.Status.IN_PROGRESS


def test_missing_panel_is_rendered_right_above_submit(client, sitting):
    start(client, sitting)
    html = client.post(f"/s/{sitting.code}/submit/", {"form_sent": "1"}).content.decode()
    panel = html.index('id="missing"')
    assert html.rindex('<fieldset class="question"') < panel < html.index('id="submit-main"')


def test_who_is_answering_stays_visible_once_started(client, sitting):
    html = take_page(client, sitting)
    who = re.search(r'<p class="who">.*?</p>', html, re.S).group(0)
    assert "Ann Lee" in who and "7-B" in who
    # also on the page that asks about empty questions (where the name fields used to vanish)
    html = client.post(f"/s/{sitting.code}/submit/", {"form_sent": "1"}).content.decode()
    assert '<p class="who">' in html and "Ann Lee" in html


def test_who_line_is_not_on_the_landing_page(client, sitting):
    html = client.get(f"/s/{sitting.code}/").content.decode()
    assert '<p class="who">' not in html and 'name="tf_name"' in html


def test_who_line_in_a_class_session_shows_the_picked_student(client, group_sitting, pupils):
    pick(client, group_sitting, pupils["ann"])
    html = client.get(f"/s/{group_sitting.code}/take/").content.decode()
    who = re.search(r'<p class="who">.*?</p>', html, re.S).group(0)
    assert "Ann Lee" in who and "7-A" in who


def test_both_live_panels_are_ready_for_the_script(client, sitting):
    html = take_page(client, sitting)
    assert 'id="missing-js"' in html and 'id="unanswered-js"' in html
    assert "__DONE__" in html  # the count sentence the script fills in
    js = (STATIC / "js" / "questions.js").read_text(encoding="utf-8")
    assert "confirm_unanswered" in js and "__DONE__" in js


# --- F-03: the navigator -----------------------------------------------------------------------


def test_navigator_has_one_button_per_question_with_states(client, sitting):
    start(client, sitting)
    html = client.post(
        f"/s/{sitting.code}/submit/", {"form_sent": "1", "q_q2": ["a"], "q_q4": "x"}
    ).content.decode()  # q1 is required and empty
    nav = re.search(r'<nav class="qnav[^"]*" id="qnav".*?</nav>', html, re.S).group(0)
    buttons = re.findall(r'<a class="qnav-btn([^"]*)" href="#q-(\w+)"', nav)
    assert sorted(qid for _cls, qid in buttons) == ["q1", "q2", "q3", "q4", "q5"]
    states = {qid: cls.split() for cls, qid in buttons}
    assert states["q2"] == ["is-done"] and states["q4"] == ["is-done"]
    assert states["q1"] == ["is-missing"] and states["q3"] == [] and states["q5"] == []
    labels = {n: label for label, n in re.findall(r'aria-label="([^"]+)">(\d+)<', nav)}
    assert sum(1 for label in labels.values() if label.endswith(", answered")) == 2
    assert all(re.fullmatch(r"Question \d+(, answered)?", label) for label in labels.values())


def test_navigator_buttons_in_the_panel_replace_text_links(client, sitting):
    start(client, sitting)
    html = client.post(
        f"/s/{sitting.code}/submit/", {"form_sent": "1", "q_q1": "a"}
    ).content.decode()
    panel = re.search(r'id="unanswered".*?</div>', html, re.S).group(0)
    assert re.findall(r'class="qnav-btn"[^>]*>(\d+)</a>', panel)
    assert "Question 2</a>" not in panel


def test_a_single_question_test_hides_the_navigator(client, teacher):
    doc = make_document()
    doc["test"]["questions"] = doc["test"]["questions"][:1]
    sitting = services.create_sitting(revision=make_revision(teacher, doc), user=teacher, title="")
    html = client.get(f"/s/{sitting.code}/").content.decode()
    assert re.search(r'<nav class="qnav[^"]*" id="qnav"[^>]*\shidden', html)


# --- F-08: one question per page ---------------------------------------------------------------


def test_one_question_per_page_flag_and_pager(client, make_sitting):
    paged = make_sitting(one_question_per_page=True)
    html = client.get(f"/s/{paged.code}/").content.decode()
    form = re.search(r"<form[^>]*id=\"take-form\"[^>]*>", html, re.S).group(0)
    assert 'data-one-per-page="1"' in form
    assert 'id="pager"' in html and "pager-next" in html
    # without the script every question is on the page, as before
    assert len(re.findall(r'<fieldset class="question"', html)) == 5
    assert not re.search(r'<fieldset class="question"[^>]*hidden', html)

    plain = make_sitting(one_question_per_page=False)
    html = Client().get(f"/s/{plain.code}/").content.decode()
    assert "data-one-per-page" not in html and 'id="pager"' not in html


def test_preview_pages_too_and_sends_nothing(client, teacher):
    revision = make_revision(teacher, make_document(one_question_per_page=True))
    client.force_login(teacher)
    html = client.get(reverse("assessments:preview", args=[revision.assessment.pk])).content
    html = html.decode()
    assert 'data-one-per-page="1"' in html and 'data-preview="1"' in html
    assert "js/questions.js" in html
    assert "js/away.js" not in html and "data-away-url" not in html


# --- F-04: leaving the page, the page side -----------------------------------------------------


@pytest.mark.parametrize("unstarted", [True, False])
def test_page_reports_leaving_and_says_so(client, sitting, unstarted):
    html = (
        client.get(f"/s/{sitting.code}/").content.decode()
        if unstarted
        else take_page(client, sitting)
    )
    assert f'data-away-url="/s/{sitting.code}/away/"' in html
    assert "js/away.js" in html
    assert "Leaving this page (for another tab or app) is recorded" in html


def test_autosave_announces_the_started_attempt_for_away_js():
    autosave = (STATIC / "js" / "autosave.js").read_text(encoding="utf-8")
    away = (STATIC / "js" / "away.js").read_text(encoding="utf-8")
    assert '"kt:started"' in autosave and '"kt:started"' in away
    assert "keepalive" in away and "X-CSRFToken" in away and "data-preview" in away


def test_new_scripts_are_small_and_self_contained():
    for name in ("questions.js", "away.js"):
        text = (STATIC / "js" / name).read_text(encoding="utf-8")
        assert not re.search(r"https?://|//cdn", text), name
        assert len(text.encode()) < 12 * 1024, name


# --- F-10: another student on this device ------------------------------------------------------


def another(client, sitting):
    return client.post(f"/s/{sitting.code}/another/")


def test_done_page_offers_another_student_while_open(client, sitting):
    start(client, sitting)
    client.post(
        f"/s/{sitting.code}/submit/", {"form_sent": "1", "q_q1": "a", "confirm_unanswered": "1"}
    )
    html = client.get(f"/s/{sitting.code}/done/").content.decode()
    assert f'action="/s/{sitting.code}/another/"' in html
    assert "Another student on this device" in html
    services.close_sitting(sitting)
    html = client.get(f"/s/{sitting.code}/done/").content.decode()
    assert "Another student on this device" not in html


def test_another_student_gets_the_landing_page_and_limits_still_hold(client, sitting):
    start(client, sitting, name="Ann Lee")
    client.post(
        f"/s/{sitting.code}/submit/", {"form_sent": "1", "q_q1": "a", "confirm_unanswered": "1"}
    )
    assert client.get(f"/s/{sitting.code}/")["Location"] == f"/s/{sitting.code}/done/"

    r = another(client, sitting)
    assert r.status_code == 302 and r["Location"] == f"/s/{sitting.code}/"
    cookie = r.cookies[f"kt_attempt_{sitting.code}"]
    assert cookie.value == "" and cookie["path"] == "/s/"

    page = client.get(f"/s/{sitting.code}/")
    assert page.status_code == 200 and 'name="tf_name"' in page.content.decode()
    # max_attempts = 1 per name: Ann cannot go again, Bob can
    again = start(client, sitting, name="ann  lee")
    assert again.status_code == 200 and "already taken this test" in again.content.decode()
    bob = start(client, sitting, name="Bob Ray")
    assert bob["Location"] == f"/s/{sitting.code}/take/"
    assert sitting.attempts.count() == 2


def test_another_never_drops_an_attempt_in_progress(client, sitting):
    start(client, sitting)
    r = another(client, sitting)
    assert r["Location"] == f"/s/{sitting.code}/take/"
    assert f"kt_attempt_{sitting.code}" not in r.cookies
    assert client.get(f"/s/{sitting.code}/take/").status_code == 200


def test_another_finishes_an_overdue_attempt_first(client, sitting):
    from datetime import timedelta

    from django.utils import timezone

    start(client, sitting)
    attempt = sitting.attempts.get()
    attempt.deadline_at = timezone.now() - timedelta(minutes=1)
    attempt.save()
    assert another(client, sitting)["Location"] == f"/s/{sitting.code}/"
    attempt.refresh_from_db()
    assert attempt.status == Attempt.Status.AUTO_SUBMITTED


def test_another_without_an_attempt_just_opens_the_test(client, sitting):
    assert another(client, sitting)["Location"] == f"/s/{sitting.code}/"


def test_another_is_post_only(client, sitting):
    assert client.get(f"/s/{sitting.code}/another/").status_code == 405


def test_class_session_next_student_picks_their_name(client, group_sitting, pupils):
    pick(client, group_sitting, pupils["ann"])
    client.post(
        f"/s/{group_sitting.code}/submit/",
        {"form_sent": "1", "q_q1": "a", "confirm_unanswered": "1"},
    )
    assert (
        "Another student on this device"
        in client.get(f"/s/{group_sitting.code}/done/").content.decode()
    )
    another(client, group_sitting)
    html = client.get(f"/s/{group_sitting.code}/").content.decode()
    assert 'name="student"' in html
    assert (
        pick(client, group_sitting, pupils["bob"])["Location"] == f"/s/{group_sitting.code}/take/"
    )
    # Ann already used her one attempt (checked from another browser: Bob is working in this one)
    assert pick(Client(), group_sitting, pupils["ann"]).status_code == 200
    assert group_sitting.attempts.filter(student=pupils["ann"]).count() == 1
