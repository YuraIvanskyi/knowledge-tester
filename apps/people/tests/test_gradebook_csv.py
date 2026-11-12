"""Gradebook CSV: the same matrix, safe for spreadsheets."""

import csv
import io
from urllib.parse import quote

import pytest
from django.urls import reverse

from apps.delivery.models import Attempt

from .gradebook_factories import (
    make_attempt,
    make_group,
    make_project,
    make_revision,
    make_sitting,
    make_student,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def group(teacher):
    return make_group(teacher, "7-A")


def download(client, group, **params):
    return client.get(reverse("people:gradebook_csv", args=[group.pk]), params)


def rows_of(response) -> list[list[str]]:
    text = response.content.decode("utf-8")
    assert text.startswith("﻿"), "the file starts with a BOM so Excel reads Cyrillic"
    return list(csv.reader(io.StringIO(text[1:], newline="")))


def test_csv_has_the_matrix_with_averages(client_for, teacher, group):
    ann = make_student(teacher, group, "Ann Lee")
    bob = make_student(teacher, group, "Bob Ray")
    s1 = make_sitting(teacher, group=group, days=0, title="Quiz 1")
    s2 = make_sitting(teacher, group=group, days=3, title="Quiz 2")
    make_attempt(s1, ann, 85)
    make_attempt(s1, ann, 70)
    make_attempt(s2, ann, "62.5")
    make_attempt(s1, bob, 35)
    response = download(client_for(teacher), group)
    assert response.status_code == 200
    assert response["Content-Type"].startswith("text/csv")
    assert "attachment" in response["Content-Disposition"]
    assert rows_of(response) == [
        ["Student", "Quiz 1 (01.09.2026)", "Quiz 2 (04.09.2026)", "Average"],
        ["Ann Lee", "85", "62.5", "73.8"],
        ["Bob Ray", "35", "", "35"],
        ["Average", "60", "62.5", "60.8"],
    ]


def test_provisional_cells_get_an_asterisk_and_a_footnote(client_for, teacher, group):
    ann = make_student(teacher, group, "Ann")
    bob = make_student(teacher, group, "Bob")
    sitting = make_sitting(teacher, group=group, title="Quiz")
    make_attempt(sitting, ann, 80, pending=3)
    make_attempt(sitting, bob, 60)
    rows = rows_of(download(client_for(teacher), group))
    assert rows[1] == ["Ann", "80*", "80*"]
    assert rows[2] == ["Bob", "60", "60"]
    assert rows[3] == ["Average", "70*", "70*"]
    assert rows[4][0].startswith("* Provisional")
    assert len(rows) == 5


def test_no_footnote_without_provisional_cells(client_for, teacher, group):
    ann = make_student(teacher, group, "Ann")
    make_attempt(make_sitting(teacher, group=group), ann, 80)
    rows = rows_of(download(client_for(teacher), group))
    assert len(rows) == 3 and "*" not in "".join("".join(r) for r in rows)


def test_formula_injection_is_neutralised(client_for, teacher, group):
    names = ['=HYPERLINK("http://evil","x")', "+1+1", "-2+3", "@SUM(A1)", "\tTab", "Normal"]
    sitting = make_sitting(teacher, group=group, title="=cmd|' /C calc'!A0")
    for name in names:
        make_attempt(sitting, make_student(teacher, group, name), 50)
    rows = rows_of(download(client_for(teacher), group))
    assert rows[0][1].startswith("'=cmd")
    got = {r[0] for r in rows[1:-1]}
    assert got == {
        '\'=HYPERLINK("http://evil","x")',
        "'+1+1",
        "'-2+3",
        "'@SUM(A1)",
        "'\tTab",
        "Normal",
    }
    for row in rows:
        for value in row:
            assert value[:1] not in ("=", "+", "-", "@", "\t", "\r")


def test_names_with_separators_quotes_and_newlines_round_trip(client_for, teacher, group):
    names = ['Smith, "Bob"', "Semi;colon", "Two\nlines", "Дем'ян Кравчук-Мельник", "O’Hara"]
    sitting = make_sitting(teacher, group=group, title='Title, with "quotes"; and more')
    for name in names:
        make_attempt(sitting, make_student(teacher, group, name), 50)
    rows = rows_of(download(client_for(teacher), group))
    assert rows[0][1].startswith('Title, with "quotes"; and more (')
    assert {r[0] for r in rows[1:-1]} == set(names)


def test_inactive_with_results_and_linked_sessions_are_included(client_for, teacher, group):
    ann = make_student(teacher, group, "Ann")
    gone = make_student(teacher, group, "Gone", active=False)
    make_student(teacher, group, "Idle gone", active=False)
    free = make_sitting(teacher, title="Free names")
    make_attempt(free, ann, 70)
    make_attempt(free, gone, 90)
    rows = rows_of(download(client_for(teacher), group))
    assert [r[0] for r in rows] == ["Student", "Ann", "Gone", "Average"]
    assert rows[1][1:] == ["70", "70"]


def test_voided_and_unfinished_attempts_are_left_out(client_for, teacher, group):
    ann = make_student(teacher, group, "Ann")
    sitting = make_sitting(teacher, group=group, title="Quiz")
    make_attempt(sitting, ann, 99, status=Attempt.Status.VOIDED)
    make_attempt(sitting, ann, 98, status=Attempt.Status.IN_PROGRESS, score=None)
    rows = rows_of(download(client_for(teacher), group))
    assert rows[1] == ["Ann", "", ""]
    assert rows[2] == ["Average", "", ""]


def test_empty_group_still_returns_a_valid_file(client_for, teacher, group):
    rows = rows_of(download(client_for(teacher), group))
    assert rows[0] == ["Student", "Average"]
    assert rows[1] == ["Average", ""]


def test_ascii_filename(client_for, teacher, group):
    header = download(client_for(teacher), group)["Content-Disposition"]
    assert header == 'attachment; filename="gradebook-7-A.csv"'


def test_cyrillic_filename_uses_filename_star(client_for, teacher):
    group = make_group(teacher, "7-Б клас “Зірки”")
    header = download(client_for(teacher), group)["Content-Disposition"]
    assert header.startswith("attachment; filename*=utf-8''")
    assert quote("gradebook-7-Б клас “Зірки”.csv") in header
    assert "\n" not in header and "\r" not in header


def test_unsafe_characters_never_reach_the_filename(client_for, teacher):
    group = make_group(teacher, 'a/b\\c:d*e?f"g<h>i|j\r\nk')
    header = download(client_for(teacher), group)["Content-Disposition"]
    assert "\n" not in header and "\r" not in header and "/" not in header.split("filename=")[1]
    assert header == 'attachment; filename="gradebook-a_b_c_d_e_f_g_h_i_j_k.csv"'
    blank = make_group(teacher, "???")
    assert download(client_for(teacher), blank)["Content-Disposition"].endswith('group.csv"')


def test_project_filter_applies_to_the_csv(client_for, teacher, group):
    ann = make_student(teacher, group, "Ann")
    maths = make_project(teacher, "Maths")
    art = make_project(teacher, "Art")
    s_maths = make_sitting(teacher, make_revision(teacher, "M", maths), group=group, title="MQ")
    s_art = make_sitting(teacher, make_revision(teacher, "A", art), group=group, title="AQ")
    make_attempt(s_maths, ann, 80)
    make_attempt(s_art, ann, 20)
    client = client_for(teacher)
    header = rows_of(download(client, group, project=maths.pk))[0]
    assert [c.split(" (")[0] for c in header[1:-1]] == ["MQ"]
    assert len(rows_of(download(client, group))[0]) == 4  # both sessions without the filter
    assert s_art.pk != s_maths.pk


def test_admin_downloads_any_groups_csv(client_for, admin_user, teacher, group):
    ann = make_student(teacher, group, "Ann")
    make_attempt(make_sitting(teacher, group=group, title="Q"), ann, 55)
    rows = rows_of(download(client_for(admin_user), group))
    assert rows[1][:2] == ["Ann", "55"]
