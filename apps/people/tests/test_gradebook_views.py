"""Gradebook page: access, content, filters, empty states, query count."""

import re

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
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


def page(client, group, **params):
    return client.get(reverse("people:gradebook", args=[group.pk]), params)


@pytest.fixture
def class_with_results(teacher, group):
    ann = make_student(teacher, group, "Ann Lee")
    bob = make_student(teacher, group, "Bob Ray")
    s1 = make_sitting(teacher, group=group, days=0, title="Quiz 1")
    s2 = make_sitting(teacher, group=group, days=3, title="Quiz 2")
    a1 = make_attempt(s1, ann, 85, grade="4")
    a2 = make_attempt(s1, bob, 35)
    a3 = make_attempt(s2, ann, 50, pending=1)
    make_attempt(s2, ann, 45)
    return {"ann": ann, "bob": bob, "s1": s1, "s2": s2, "attempts": (a1, a2, a3)}


# ---- access ---------------------------------------------------------------------------------


def test_login_is_required(client, group):
    for name in ("people:gradebook", "people:gradebook_csv"):
        response = client.get(reverse(name, args=[group.pk]))
        assert response.status_code == 302
        assert response["Location"].startswith(reverse("accounts:login"))


def test_a_foreign_group_is_a_404_for_page_and_csv(client_for, other_teacher, group):
    client = client_for(other_teacher)
    assert page(client, group).status_code == 404
    assert client.get(reverse("people:gradebook_csv", args=[group.pk])).status_code == 404
    assert client.get(reverse("people:gradebook", args=[999999])).status_code == 404


def test_the_owner_and_an_admin_can_open_it(client_for, teacher, admin_user, group):
    assert page(client_for(teacher), group).status_code == 200
    assert page(client_for(admin_user), group).status_code == 200


def test_post_is_not_allowed(client_for, teacher, group):
    client = client_for(teacher)
    assert client.post(reverse("people:gradebook", args=[group.pk])).status_code == 405
    assert client.post(reverse("people:gradebook_csv", args=[group.pk])).status_code == 405


def test_the_foreign_group_name_does_not_leak(client_for, other_teacher, teacher):
    secret = make_group(teacher, "Secret class")
    response = page(client_for(other_teacher), secret)
    assert response.status_code == 404
    assert b"Secret class" not in response.content


# ---- content --------------------------------------------------------------------------------


def test_matrix_shows_names_percentages_links_and_averages(
    client_for, teacher, group, class_with_results
):
    html = page(client_for(teacher), group).content.decode()
    s1, s2 = class_with_results["s1"], class_with_results["s2"]
    a1, a2, a3 = class_with_results["attempts"]
    assert "Gradebook: 7-A" in html
    assert "Ann Lee" in html and "Bob Ray" in html
    assert reverse("reports:session", args=[s1.pk]) in html
    assert reverse("reports:session", args=[s2.pk]) in html
    for attempt in (a1, a2, a3):
        assert reverse("reports:attempt", args=[attempt.pk]) in html
    assert reverse("people:student", args=[class_with_results["ann"].pk]) in html
    assert "85&nbsp;%" in html and "35&nbsp;%" in html
    # Ann: best of Quiz 2 is the provisional 50 (not the 45); average of 85 and 50
    assert "67.5&nbsp;%" in html
    assert "50&nbsp;%" in html and "45&nbsp;%" not in html
    assert "&times;2" in html  # two attempts in Quiz 2
    assert "status-ok" in html and "status-warn" in html and "status-bad" in html
    assert "2&nbsp;/&nbsp;2" in html and "1&nbsp;/&nbsp;2" in html  # who took each session
    assert "2 students" in html and "2 sessions" in html


def test_page_states_the_rule_and_explains_the_markers(
    client_for, teacher, group, class_with_results
):
    html = page(client_for(teacher), group).content.decode()
    assert "best finished attempt" in html
    assert "60 % and above: good" in html
    assert "40 % to below 60 %: fair" in html
    assert "below 40 %: weak" in html
    assert "provisional: some answers still wait for review" in html
    assert "best attempt is shown" in html
    assert "the grade of the best attempt, as set by the test" in html  # grade 4 is shown
    assert re.search(r'class="gb-flag"[^>]*>\*<', html)  # the provisional marker
    assert "Swipe sideways" in html


def test_percent_scale_grades_are_not_repeated_in_the_cell(client_for, teacher, group):
    ann = make_student(teacher, group, "Ann")
    make_attempt(make_sitting(teacher, group=group), ann, 70, grade="70.0 %")
    html = page(client_for(teacher), group).content.decode()
    assert "70&nbsp;%" in html and "70.0 %" not in html
    assert "the grade of the best attempt" not in html
    assert "best attempt is shown" not in html  # no repeated attempts either


def test_cells_carry_a_word_next_to_the_colour(client_for, teacher, group, class_with_results):
    html = page(client_for(teacher), group).content.decode()
    assert re.search(r'visually-hidden">\s*good', html)  # 85 %
    assert re.search(r'visually-hidden">\s*fair, provisional, best of 2 attempts', html)  # 50 %
    assert re.search(r'visually-hidden">\s*weak', html)  # 35 %


def test_the_session_not_bound_to_the_group_is_marked_linked(client_for, teacher, group):
    ann = make_student(teacher, group, "Ann")
    free = make_sitting(teacher, title="Free names")
    make_attempt(free, ann, 77)
    html = page(client_for(teacher), group).content.decode()
    assert "Free names" in html and "linked" in html and "77&nbsp;%" in html


def test_plural_counts_and_inactive_marker(client_for, teacher, group):
    ann = make_student(teacher, group, "Ann")
    gone = make_student(teacher, group, "Gone Away", active=False)
    sitting = make_sitting(teacher, group=group)
    make_attempt(sitting, ann, 70)
    make_attempt(sitting, gone, 90)
    html = page(client_for(teacher), group).content.decode()
    assert "2 students" in html and "1 session" in html and "1 sessions" not in html
    assert "inactive" in html
    assert html.index("Ann") < html.index("Gone Away")


def test_names_and_titles_are_escaped(client_for, teacher, group):
    evil = make_student(teacher, group, "<script>alert(1)</script> O'Brien")
    sitting = make_sitting(teacher, group=group, title="<b>bold</b>")
    make_attempt(sitting, evil, 50)
    html = page(client_for(teacher), group).content.decode()
    assert "<script>alert(1)" not in html and "<b>bold</b>" not in html
    assert "&lt;script&gt;" in html


def test_ukrainian_names_with_apostrophes_render(client_for, teacher, group):
    student = make_student(teacher, group, "Дем’ян Кравчук-Мельник")
    sitting = make_sitting(teacher, group=group, title="Контрольна №1")
    make_attempt(sitting, student, 66)
    html = page(client_for(teacher), group).content.decode()
    assert "Дем’ян Кравчук-Мельник" in html and "Контрольна №1" in html


def test_page_is_translated_into_ukrainian_when_asked(client_for, teacher, group):
    client = client_for(teacher)
    client.cookies["django_language"] = "uk"
    response = page(client, group)
    assert response.status_code == 200
    assert response["Content-Language"] == "uk"


def test_empty_group_has_links_to_the_group_page(client_for, teacher, group):
    html = page(client_for(teacher), group).content.decode()
    assert "This group has no students yet." in html
    assert reverse("people:group", args=[group.pk]) in html
    assert "gb-table" not in html and "Download CSV" not in html


def test_group_without_sessions_points_to_starting_one(client_for, teacher, group):
    make_student(teacher, group, "Ann")
    html = page(client_for(teacher), group).content.decode()
    assert "No sessions for this group yet" in html
    assert reverse("people:group", args=[group.pk]) in html
    assert reverse("assessments:list") in html
    assert "gb-table" not in html


# ---- filters --------------------------------------------------------------------------------


def test_project_filter_limits_the_columns_and_lists_only_own_projects(
    client_for, teacher, other_teacher, group
):
    ann = make_student(teacher, group, "Ann")
    maths = make_project(teacher, "Maths")
    art = make_project(teacher, "Art history")
    make_project(other_teacher, "Foreign project")
    s_maths = make_sitting(teacher, make_revision(teacher, "M", maths), group=group, title="MQ")
    s_art = make_sitting(teacher, make_revision(teacher, "A", art), group=group, title="AQ")
    make_attempt(s_maths, ann, 80)
    make_attempt(s_art, ann, 20)
    client = client_for(teacher)
    html = page(client, group, project=maths.pk).content.decode()
    assert reverse("reports:session", args=[s_maths.pk]) in html
    assert reverse("reports:session", args=[s_art.pk]) not in html
    assert "Foreign project" not in html
    assert "Maths" in html and "Art history" in html  # both in the dropdown
    assert f'value="{maths.pk}" selected' in html
    assert "Reset" in html
    unfiltered = page(client, group).content.decode()
    assert reverse("reports:session", args=[s_art.pk]) in unfiltered


def test_a_foreign_or_unknown_project_is_a_404(client_for, teacher, other_teacher, group):
    foreign = make_project(other_teacher, "Foreign project")
    client = client_for(teacher)
    for url in (
        reverse("people:gradebook", args=[group.pk]),
        reverse("people:gradebook_csv", args=[group.pk]),
    ):
        assert client.get(url, {"project": foreign.pk}).status_code == 404
        assert client.get(url, {"project": 999999}).status_code == 404


def test_garbage_filters_are_ignored(client_for, teacher, group, class_with_results):
    client = client_for(teacher)
    html = page(client, group, project="abc", since="not-a-date").content.decode()
    assert "Ann Lee" in html and "Quiz 1" in html
    assert page(client, group, project="", since="2026-13-45").status_code == 200


def test_since_filter(client_for, teacher, group, class_with_results):
    client = client_for(teacher)
    html = page(client, group, since="2026-09-02").content.decode()  # Quiz 1 is 2026-09-01 (UTC)
    assert "Quiz 2" in html and "Quiz 1" not in html
    assert 'value="2026-09-02"' in html
    nothing = page(client, group, since="2030-01-01").content.decode()
    assert "No sessions match this filter." in nothing


def test_filters_are_carried_into_the_csv_link(client_for, teacher, group):
    ann = make_student(teacher, group, "Ann")
    maths = make_project(teacher, "Maths")
    sitting = make_sitting(teacher, make_revision(teacher, "M", maths), group=group)
    make_attempt(sitting, ann, 80)
    html = page(client_for(teacher), group, project=maths.pk, since="2026-01-01").content.decode()
    csv_path = reverse("people:gradebook_csv", args=[group.pk])
    assert f"{csv_path}?project={maths.pk}&amp;since=2026-01-01" in html


# ---- other teachers' data and the query count ----------------------------------------------


def test_foreign_sessions_linked_by_an_admin_stay_hidden_from_the_teacher(
    client_for, teacher, other_teacher, group
):
    ann = make_student(teacher, group, "Ann")
    foreign = make_sitting(other_teacher, title="Foreign quiz")
    make_attempt(foreign, ann, 12)
    assert b"Foreign quiz" not in page(client_for(teacher), group).content


def test_query_count_does_not_grow_with_the_class(client_for, teacher, group):
    client = client_for(teacher)
    client.get(reverse("core:dashboard"))  # warm up (content types, session) before counting
    ann = make_student(teacher, group, "Ann")
    first = make_sitting(teacher, group=group)
    make_attempt(first, ann, 70)

    def count():
        with CaptureQueriesContext(connection) as ctx:
            assert page(client, group).status_code == 200
        return len(ctx)

    small = count()
    for i in range(15):
        student = make_student(teacher, group, f"Student {i:02d}")
        sitting = make_sitting(teacher, group=group, days=i + 1)
        for s in (first, sitting):
            make_attempt(s, student, 60)
            make_attempt(s, student, 80, pending=1)
    assert count() == small
    assert small <= 9


def test_attempts_of_a_different_status_do_not_break_the_page(client_for, teacher, group):
    ann = make_student(teacher, group, "Ann")
    sitting = make_sitting(teacher, group=group)
    make_attempt(sitting, ann, 70, status=Attempt.Status.VOIDED)
    html = page(client_for(teacher), group).content.decode()
    assert "Ann" in html and "gb-table" in html


def test_a_big_class_renders_quickly(client_for, teacher, group):
    from time import perf_counter

    from .gradebook_factories import attempt_fields

    students = [make_student(teacher, group, f"Student {i:02d}") for i in range(40)]
    sittings = [make_sitting(teacher, group=group, days=i) for i in range(20)]
    Attempt.objects.bulk_create(
        Attempt(**attempt_fields(s, student, 30 + (i * 7 + j * 3) % 70, grade="4"))
        for i, student in enumerate(students)
        for j, s in enumerate(sittings)
    )
    client = client_for(teacher)
    started = perf_counter()
    response = page(client, group)
    csv_response = client.get(reverse("people:gradebook_csv", args=[group.pk]))
    elapsed = perf_counter() - started
    assert response.status_code == 200 and csv_response.status_code == 200
    assert response.content.count(b'class="gb-link') == 800
    print(f"page + csv for 40 x 20: {elapsed:.2f}s")
    assert elapsed < 2.0


def test_a_huge_project_id_is_a_404_not_a_crash(client_for, teacher, group):
    client = client_for(teacher)
    assert page(client, group, project="9" * 40).status_code == 404
    assert page(client, group, project="٣").status_code == 404  # non-ASCII digits: not a project
