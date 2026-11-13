"""The results CSV always names the taker, whatever fields the test asks for."""

import copy
import csv
import io

import pytest
from django.urls import reverse

from apps.assessments.models import Revision
from apps.delivery.models import Attempt

from .test_views import DOC, login, make_attempt, sitting, teacher  # noqa: F401

pytestmark = pytest.mark.django_db


def csv_rows(client, the_sitting):
    response = client.get(reverse("reports:csv", args=[the_sitting.pk]))
    text = response.content.decode("utf-8").lstrip("﻿")
    return list(csv.reader(io.StringIO(text)))


def with_taker_fields(the_sitting, fields):
    doc = copy.deepcopy(DOC)
    doc["test"]["taker_fields"] = fields
    Revision.objects.filter(pk=the_sitting.revision_id).update(document=doc)
    the_sitting.revision.refresh_from_db()


def test_name_column_is_added_when_the_test_has_no_name_field(login, sitting):  # noqa: F811
    """A class session stores the picked student's name even if the test only asks for a class."""
    with_taker_fields(sitting, [{"key": "class", "label": "Class"}])
    make_attempt(sitting, "Ivan", {"q1": ["a"]})
    header, row = csv_rows(login, sitting)[:2]
    assert header[:2] == ["Name", "Class"]
    assert row[:2] == ["Ivan", "7-A"]


def test_no_taker_fields_still_gives_a_name_column(login, sitting):  # noqa: F811
    with_taker_fields(sitting, [])
    make_attempt(sitting, "Olena", {"q1": ["a"]})
    header, row = csv_rows(login, sitting)[:2]
    assert header[0] == "Name" and row[0] == "Olena"


def test_other_keys_the_attempts_carry_are_appended(login, sitting):  # noqa: F811
    with_taker_fields(sitting, [{"key": "name", "label": "Full name"}])
    make_attempt(sitting, "Ivan", {"q1": ["a"]})  # taker also has "class"
    header, row = csv_rows(login, sitting)[:2]
    assert header[:2] == ["Full name", "class"]
    assert row[:2] == ["Ivan", "7-A"]


def test_the_usual_test_is_unchanged(login, sitting):  # noqa: F811
    make_attempt(sitting, "Ivan", {"q1": ["a"]})
    header = csv_rows(login, sitting)[0]
    assert header[:2] == ["Full name", "Class"]
    assert Attempt.objects.count() == 1
