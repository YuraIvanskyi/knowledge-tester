"""F-09: previous / next between attempt sheets, in the order of the results table."""

from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.delivery.models import Attempt
from apps.reports import data

from .test_views import login, make_attempt, sitting, teacher  # noqa: F401 - fixtures

pytestmark = pytest.mark.django_db


@pytest.fixture
def four(sitting):  # noqa: F811
    """Started in this order: Bob (needs review), Ann, Cleo (cancelled), Dan (working)."""
    base = timezone.now() - timedelta(minutes=30)
    bob = make_attempt(sitting, "Bob", {"q1": ["a"], "q3": "An open answer"})
    ann = make_attempt(sitting, "Ann", {"q1": ["b"]})
    cleo = make_attempt(sitting, "Cleo", {"q1": ["a"]}, status=Attempt.Status.VOIDED)
    dan = make_attempt(sitting, "Dan", {}, status=Attempt.Status.IN_PROGRESS)
    for minutes, attempt in enumerate([bob, ann, cleo, dan]):
        Attempt.objects.filter(pk=attempt.pk).update(started_at=base + timedelta(minutes=minutes))
    return {a.taker["name"]: Attempt.objects.get(pk=a.pk) for a in (bob, ann, cleo, dan)}


def nav_of(client, attempt, query=""):
    page = client.get(reverse("reports:attempt", args=[attempt.pk]) + query)
    assert page.status_code == 200
    return page.context["nav"], page.content.decode()


def test_steps_follow_the_start_time_by_default(login, four):  # noqa: F811
    nav, html = nav_of(login, four["Bob"])
    assert (nav.previous, nav.next.pk, nav.position, nav.total) == (None, four["Ann"].pk, 1, 3)
    assert 'id="sheet-prev"' not in html and 'id="sheet-next"' in html
    assert "1 of 3" in html
    nav, html = nav_of(login, four["Ann"])
    assert (nav.previous.pk, nav.next.pk) == (four["Bob"].pk, four["Dan"].pk)
    nav, html = nav_of(login, four["Dan"])
    assert nav.next is None and nav.position == 3
    assert 'id="sheet-next"' not in html  # the end: no link, only the greyed arrow
    assert "js/sheetnav.js" in html


def test_steps_follow_the_sort_and_filter_and_keep_them(login, four):  # noqa: F811
    nav, html = nav_of(login, four["Ann"], "?sort=name&status=finished")
    assert (nav.previous, nav.next.pk, nav.total) == (None, four["Bob"].pk, 2)
    url = reverse("reports:attempt", args=[four["Bob"].pk])
    assert f'href="{url}?status=finished&amp;sort=name"' in html
    # back to the same table
    session_url = reverse("reports:session", args=[four["Ann"].sitting_id])
    assert f"{session_url}?status=finished&amp;sort=name" in html


def test_results_table_links_carry_filter_and_sort(login, sitting, four):  # noqa: F811
    html = login.get(
        reverse("reports:session", args=[sitting.pk]) + "?sort=-name&status=finished"
    ).content.decode()
    url = reverse("reports:attempt", args=[four["Ann"].pk])
    assert f"{url}?status=finished&amp;sort=-name" in html
    # defaults add nothing
    html = login.get(reverse("reports:session", args=[sitting.pk])).content.decode()
    assert f'href="{url}"' in html


def test_unknown_query_values_fall_back_to_the_defaults(login, four):  # noqa: F811
    nav, html = nav_of(login, four["Ann"], "?sort=evil&status=<x>")
    assert nav.total == 3
    url = reverse("reports:attempt", args=[four["Dan"].pk])
    assert f'id="sheet-next" rel="next" href="{url}"' in html  # nothing of the query is echoed


def test_a_sheet_outside_the_filter_is_placed_by_the_sort(sitting, four):  # noqa: F811
    attempts = list(sitting.attempts.all())
    # Ann has no pending review, so "needs review" lists only Bob; Ann still steps back to Bob
    nav = data.neighbours(four["Ann"], attempts, "needs_review", "time")
    assert (nav.previous.pk, nav.next, nav.position, nav.total) == (four["Bob"].pk, None, 2, 2)
    # a cancelled sheet opened from "all"
    nav = data.neighbours(four["Cleo"], attempts, "all", "time")
    assert (nav.previous.pk, nav.next.pk) == (four["Ann"].pk, four["Dan"].pk)


def test_only_one_result_shows_no_steps(login, sitting):  # noqa: F811
    alone = make_attempt(sitting, "Solo", {"q1": ["a"]})
    _nav, html = nav_of(login, alone)
    assert "sheet-steps" not in html


def test_saving_a_review_keeps_the_query(login, four):  # noqa: F811
    bob = four["Bob"]
    url = reverse("reports:attempt", args=[bob.pk]) + "?status=needs_review"
    r = login.post(url, {"points_q3": "2", "comment_q3": "", "action": "save"})
    assert r.status_code == 302 and r["Location"] == url
    r = login.post(url, {"points_q3": "3", "comment_q3": "", "action": "next"})
    session_url = reverse("reports:session", args=[bob.sitting_id])
    assert r["Location"] == session_url + "?status=needs_review"


def test_sheet_says_whether_the_student_left_the_page(login, four):  # noqa: F811
    _nav, html = nav_of(login, four["Ann"])
    assert "Left the test page" in html and "never" in html
    Attempt.objects.filter(pk=four["Ann"].pk).update(away_count=3, away_seconds=80)
    _nav, html = nav_of(login, four["Ann"])
    assert "3 times (1 min 20 s)" in html
    assert "Left the test page 3 times, 1 min 20 s in total" in html  # the tooltip
