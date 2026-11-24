"""F-04 on the results pages: the away column of the results table and the CSV columns."""

import csv
import io

import pytest
from django.urls import reverse

from apps.delivery.models import Attempt

from .test_views import login, make_attempt, sitting, teacher  # noqa: F401 - fixtures

pytestmark = pytest.mark.django_db


def results(client, sitting):  # noqa: F811
    return client.get(reverse("reports:session", args=[sitting.pk])).content.decode()


def test_results_table_shows_the_column_only_when_someone_left(login, sitting):  # noqa: F811
    ann = make_attempt(sitting, "Ann", {"q1": ["a"]})
    make_attempt(sitting, "Bob", {"q1": ["b"]})
    html = results(login, sitting)
    assert "Left the page" not in html
    Attempt.objects.filter(pk=ann.pk).update(away_count=4, away_seconds=125)
    html = results(login, sitting)
    assert '<th scope="col">Left the page</th>' in html
    assert "&#8599; 4 · 2:05" in html
    assert "Left the test page 4 times, 2 min 5 s in total" in html
    assert html.count("away-none") == 1  # Bob's cell, hidden on phone cards


def test_csv_has_the_away_columns_before_the_questions(login, sitting):  # noqa: F811
    ann = make_attempt(sitting, "Ann", {"q1": ["a"]})
    Attempt.objects.filter(pk=ann.pk).update(away_count=2, away_seconds=30)
    make_attempt(sitting, "Bob", {"q1": ["b"]})
    body = login.get(reverse("reports:csv", args=[sitting.pk])).content.decode("utf-8-sig")
    rows = list(csv.reader(io.StringIO(body)))
    header = rows[0]
    at = header.index("Pending reviews")
    # after the extra points and their reason
    assert header[at + 3 : at + 5] == ["Left the page (times)", "Away (seconds)"]
    assert header[at + 5] == "1. q1"
    by_name = {r[0]: dict(zip(header, r, strict=True)) for r in rows[1:]}
    assert (by_name["Ann"]["Left the page (times)"], by_name["Ann"]["Away (seconds)"]) == (
        "2",
        "30",
    )
    assert by_name["Bob"]["Left the page (times)"] == "0"
