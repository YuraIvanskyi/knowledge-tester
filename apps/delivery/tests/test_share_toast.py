"""F-05 and F-04 on the share screen: stats for the "handed in" notes and the away badge."""

import pytest
from django.urls import reverse
from django.utils import translation

from apps.delivery import services
from apps.delivery.models import Attempt

pytestmark = pytest.mark.django_db


@pytest.fixture
def teacher_client(client, teacher):
    client.force_login(teacher)
    return client


def test_stats_carry_ids_finish_times_and_away_data(teacher_client, sitting):
    ann = services.start_attempt(sitting, {"name": "Ann"})
    bob = services.start_attempt(sitting, {"name": "Bob"})
    services.record_away(bob, 3, 80)
    services.finalize(ann)
    data = teacher_client.get(reverse("delivery:stats", args=[sitting.pk])).json()
    takers = {t["name"]: t for t in data["takers"]}
    assert takers["Ann"]["id"] == ann.pk and takers["Ann"]["submitted_at"]
    assert takers["Ann"]["away_count"] == 0 and takers["Ann"]["away_text"] == ""
    assert takers["Bob"]["submitted_at"] is None
    assert (takers["Bob"]["away_count"], takers["Bob"]["away_seconds"]) == (3, 80)
    assert takers["Bob"]["away_short"] == "3 · 1:20"
    assert takers["Bob"]["away_text"] == "Left the test page 3 times, 1 min 20 s in total"
    # every key the page already used is still there
    assert {"name", "status", "status_label", "answered", "total", "variant", "group"} <= set(
        takers["Bob"]
    )


def test_voided_attempts_are_never_announced(teacher_client, sitting):
    ann = services.start_attempt(sitting, {"name": "Ann"})
    services.finalize(ann)
    services.void_attempt(ann)
    data = teacher_client.get(reverse("delivery:stats", args=[sitting.pk])).json()
    assert data["takers"] == []


def test_share_page_knows_what_was_finished_before(teacher_client, sitting):
    ann = services.start_attempt(sitting, {"name": "Ann"})
    bob = services.start_attempt(sitting, {"name": "Bob"})
    cleo = services.start_attempt(sitting, {"name": "Cleo"})
    services.finalize(ann)
    services.finalize(cleo, Attempt.Status.AUTO_SUBMITTED)
    html = teacher_client.get(reverse("delivery:share", args=[sitting.pk])).content.decode()
    finished = html.split('data-finished="')[1].split('"')[0].split(",")
    assert sorted(finished) == sorted([str(ann.pk), str(cleo.pk)]) and str(bob.pk) not in finished
    assert 'data-poll="5000"' in html
    assert 'id="toasts"' in html and 'role="status"' in html
    assert 'data-caption="Work handed in"' in html
    assert 'data-caption-auto="Handed in automatically"' in html


def test_presentation_mode_polls_faster_and_has_the_notes(teacher_client, sitting):
    html = teacher_client.get(
        reverse("delivery:share", args=[sitting.pk]) + "?present=1"
    ).content.decode()
    assert 'data-poll="3000"' in html and 'id="toasts"' in html
    assert 'data-finished=""' in html  # nobody yet: every finish will be announced


def test_takers_table_shows_the_away_badge(teacher_client, sitting):
    ann = services.start_attempt(sitting, {"name": "Ann"})
    services.start_attempt(sitting, {"name": "Bob"})
    url = reverse("delivery:share", args=[sitting.pk])
    html = teacher_client.get(url).content.decode()
    assert '<th scope="col">Left the page</th>' in html
    assert "away-badge" not in html
    assert 'id="away-note" class="muted away-note" hidden' in html
    services.record_away(ann, 2, 45)
    html = teacher_client.get(url).content.decode()
    assert html.count("away-badge") == 1 and "&#8599; 2 · 0:45" in html
    assert "Left the test page 2 times, 45 s in total" in html
    assert 'id="away-note" class="muted away-note">' in html
    assert html.count("away-none") == 1  # Bob: hidden on phone cards


@pytest.mark.parametrize(
    "seconds, words, clock",
    [
        (0, "0 s", "0:00"),
        (45, "45 s", "0:45"),
        (80, "1 min 20 s", "1:20"),
        (3600 + 5 * 60 + 20, "1 h 5 min", "1:05:20"),
        (-3, "0 s", "0:00"),
    ],
)
def test_away_formats(seconds, words, clock):
    assert services.away_duration(seconds) == words
    assert services.away_clock(seconds) == clock


def test_away_text_singular_and_none():
    assert services.away_text(0, 50) == ""
    assert services.away_text(1, 5) == "Left the test page 1 time, 5 s in total"


def test_away_text_in_ukrainian_uses_the_plural_forms():
    with translation.override("uk"):
        text = services.away_text(3, 80)
    # untranslated until the orchestrator merges the catalog: then it is Ukrainian
    assert "3" in text and "1" in text
