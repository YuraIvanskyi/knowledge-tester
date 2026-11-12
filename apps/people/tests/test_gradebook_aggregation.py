"""Gradebook aggregation: which sessions and students, which attempt counts, the averages."""

from datetime import date
from decimal import Decimal
from time import perf_counter

import pytest

from apps.delivery.models import Attempt
from apps.people.gradebook import alpha_key, band, build_gradebook, mean

from .gradebook_factories import (
    BASE_TIME,
    attempt_fields,
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
    return make_group(teacher)


def cell(book, student, column=0):
    row = next(r for r in book.rows if r.student.pk == student.pk)
    return row.cells[column]


def test_best_attempt_wins_and_counts_attempts(teacher, group):
    ann = make_student(teacher, group, "Ann")
    sitting = make_sitting(teacher, group=group)
    make_attempt(sitting, ann, 40)
    best = make_attempt(sitting, ann, 85, grade="4")
    make_attempt(sitting, ann, 70)
    book = build_gradebook(group)
    c = cell(book, ann)
    assert c.percent == Decimal("85")
    assert c.attempt_id == best.pk
    assert c.attempts == 3
    assert c.grade == "4" and c.show_grade
    assert not c.provisional
    assert book.has_multiple and book.has_grades


def test_a_tie_goes_to_the_finished_attempt_then_the_later_one(teacher, group):
    ann = make_student(teacher, group, "Ann")
    sitting = make_sitting(teacher, group=group)
    make_attempt(sitting, ann, 70, pending=1)
    done = make_attempt(sitting, ann, 70)
    assert cell(build_gradebook(group), ann).attempt_id == done.pk
    later = make_attempt(sitting, ann, 70)
    assert cell(build_gradebook(group), ann).attempt_id == later.pk


def test_only_counted_attempts_fill_a_cell(teacher, group):
    ann, bob, cy, dee, eve = (
        make_student(teacher, group, n) for n in ("Ann", "Bob", "Cy", "Dee", "Eve")
    )
    sitting = make_sitting(teacher, group=group)
    make_attempt(sitting, ann, 90, status=Attempt.Status.VOIDED)
    make_attempt(sitting, bob, 90, status=Attempt.Status.IN_PROGRESS, score=None)
    make_attempt(sitting, cy, None, score=None)  # submitted but ungraded
    make_attempt(sitting, dee, 55, status=Attempt.Status.AUTO_SUBMITTED)
    book = build_gradebook(group)
    assert cell(book, ann) is None
    assert cell(book, bob) is None
    assert cell(book, cy) is None
    assert cell(book, dee).percent == Decimal("55")
    assert cell(book, eve) is None
    assert book.columns[0].takers == 1


def test_voided_best_attempt_does_not_hide_a_lower_valid_one(teacher, group):
    ann = make_student(teacher, group, "Ann")
    sitting = make_sitting(teacher, group=group)
    make_attempt(sitting, ann, 95, status=Attempt.Status.VOIDED)
    make_attempt(sitting, ann, 50)
    c = cell(build_gradebook(group), ann)
    assert c.percent == Decimal("50")
    assert c.attempts == 1


def test_pending_reviews_make_a_cell_and_its_averages_provisional(teacher, group):
    ann = make_student(teacher, group, "Ann")
    bob = make_student(teacher, group, "Bob")
    s1 = make_sitting(teacher, group=group, days=0)
    s2 = make_sitting(teacher, group=group, days=1)
    make_attempt(s1, ann, 80, pending=2)
    make_attempt(s1, bob, 60)
    make_attempt(s2, bob, 70)
    book = build_gradebook(group)
    assert cell(book, ann, 0).provisional
    assert not cell(book, bob, 0).provisional
    rows = {r.student.full_name: r for r in book.rows}
    assert rows["Ann"].provisional and not rows["Bob"].provisional
    assert book.columns[0].provisional and not book.columns[1].provisional
    assert book.overall_provisional and book.has_provisional


def test_columns_are_sessions_of_several_tests_oldest_first(teacher, group):
    ann = make_student(teacher, group, "Ann")
    late = make_sitting(teacher, group=group, days=9, title="Final", test_title="Exam")
    early = make_sitting(teacher, group=group, days=1, title="", test_title="Fractions")
    mid = make_sitting(teacher, group=group, days=4, title="Quiz 2", test_title="Fractions")
    for s, p in ((late, 90), (early, 50), (mid, 70)):
        make_attempt(s, ann, p)
    book = build_gradebook(group)
    assert [c.sitting_id for c in book.columns] == [early.pk, mid.pk, late.pk]
    first, second, third = book.columns
    assert first.title == "Fractions" and first.subtitle == ""  # no session title: the test's
    assert second.title == "Quiz 2" and second.test_title == "Fractions"
    assert second.subtitle == "Fractions"
    assert third.title == "Final" and third.subtitle == "Exam"
    assert first.date == date(2026, 9, 2)
    assert first.code == early.code
    assert all(c.bound for c in book.columns)
    assert [c.percent for c in book.rows[0].cells] == [Decimal(50), Decimal(70), Decimal(90)]


def test_a_session_linked_after_the_fact_is_a_column(teacher, group):
    ann = make_student(teacher, group, "Ann")
    bob = make_student(teacher, group, "Bob")
    bound = make_sitting(teacher, group=group, days=0)
    free = make_sitting(teacher, days=1, title="Free names")
    make_attempt(free, ann, 65)
    make_attempt(free, bob, 45)
    book = build_gradebook(group)
    assert [c.sitting_id for c in book.columns] == [bound.pk, free.pk]
    assert [c.bound for c in book.columns] == [True, False]
    assert cell(book, ann, 0) is None
    assert cell(book, ann, 1).percent == Decimal(65)


def test_a_session_only_with_voided_links_is_not_a_column(teacher, group):
    ann = make_student(teacher, group, "Ann")
    free = make_sitting(teacher, title="Free")
    make_attempt(free, ann, 65, status=Attempt.Status.VOIDED)
    assert build_gradebook(group).columns == []
    make_attempt(free, ann, None, status=Attempt.Status.IN_PROGRESS, score=None)
    book = build_gradebook(group)  # a running attempt counts for the column, not for a cell
    assert [c.sitting_id for c in book.columns] == [free.pk]
    assert cell(book, ann) is None


def test_other_groups_and_students_do_not_leak_in(teacher, group):
    ann = make_student(teacher, group, "Ann")
    other_group = make_group(teacher, "8-B")
    stranger = make_student(teacher, other_group, "Stranger")
    loose = make_student(teacher, None, "Loose")
    mine = make_sitting(teacher, group=group)
    theirs = make_sitting(teacher, group=other_group, days=1)
    make_attempt(mine, ann, 70)
    make_attempt(mine, stranger, 10)
    make_attempt(mine, loose, 20)
    make_attempt(theirs, stranger, 30)
    book = build_gradebook(group)
    assert [r.student.full_name for r in book.rows] == ["Ann"]
    assert [c.sitting_id for c in book.columns] == [mine.pk]
    assert book.columns[0].takers == 1
    assert book.overall_average == Decimal("70.0")


def test_inactive_student_is_a_row_only_with_results_and_comes_last(teacher, group):
    old_with = make_student(teacher, group, "Zoya", active=False)
    old_without = make_student(teacher, group, "Yarko", active=False)
    active = make_student(teacher, group, "Ann")
    sitting = make_sitting(teacher, group=group)
    make_attempt(sitting, old_with, 75)
    names = [r.student.full_name for r in build_gradebook(group).rows]
    assert names == ["Ann", "Zoya"]
    assert old_without.pk not in [r.student.pk for r in build_gradebook(group).rows]
    assert active.is_active


def test_rows_follow_the_ukrainian_alphabet(teacher, group):
    names = ["Олена", "Іван", "Андрій", "Ґалина", "Єва", "Яна", "Ірина", "Ярослав", "Юля"]
    for n in names:
        make_student(teacher, group, n)
    got = [r.student.full_name for r in build_gradebook(group).rows]
    assert got == ["Андрій", "Ґалина", "Єва", "Іван", "Ірина", "Олена", "Юля", "Яна", "Ярослав"]


def test_alpha_key_ignores_case_and_apostrophe_style():
    assert alpha_key("дем’ян") == alpha_key("ДЕМ'ЯН")
    assert alpha_key("Іван") < alpha_key("Яна")
    assert alpha_key("Anna") < alpha_key("Андрій")  # Latin before Cyrillic, consistently


def test_empty_group_and_group_without_sessions(teacher, group):
    book = build_gradebook(group)
    assert book.is_empty and book.rows == [] and book.columns == []
    assert book.overall_average is None and not book.has_provisional
    make_student(teacher, group, "Ann")
    book = build_gradebook(group)
    assert [r.student.full_name for r in book.rows] == ["Ann"]
    assert book.columns == [] and book.is_empty
    assert book.rows[0].average is None
    make_sitting(teacher, group=group)
    book = build_gradebook(group)
    assert not book.is_empty  # a bound session with nobody done yet is still a column
    assert book.columns[0].takers == 0 and book.columns[0].average is None
    assert book.rows[0].cells == [None]


def test_average_maths_rounds_half_up_to_one_decimal(teacher, group):
    ann = make_student(teacher, group, "Ann")
    bob = make_student(teacher, group, "Bob")
    s1 = make_sitting(teacher, group=group, days=0)
    s2 = make_sitting(teacher, group=group, days=1)
    make_attempt(s1, ann, "60.0")
    make_attempt(s2, ann, "75.5")  # mean 67.75 -> 67.8 (banker's rounding would give 67.8 too)
    make_attempt(s1, bob, "62.5")
    make_attempt(s2, bob, "61.5")  # mean 62.0
    book = build_gradebook(group)
    rows = {r.student.full_name: r for r in book.rows}
    assert rows["Ann"].average == Decimal("67.8")
    assert rows["Bob"].average == Decimal("62.0")
    assert rows["Ann"].filled == 2
    assert book.columns[0].average == Decimal("61.3")  # (60 + 62.5) / 2 = 61.25 -> 61.3
    assert book.columns[1].average == Decimal("68.5")  # (75.5 + 61.5) / 2
    # the overall average is the mean of the four cells, not the mean of the two means
    assert book.overall_average == Decimal("64.9")  # 259.5 / 4 = 64.875
    assert isinstance(book.overall_average, Decimal)


def test_mean_helper():
    assert mean([]) is None
    assert mean([Decimal("33.3"), Decimal("33.3"), Decimal("33.4")]) == Decimal("33.3")
    assert mean([Decimal("0.05")]) == Decimal("0.1")
    assert mean([Decimal(1), Decimal(2)]) == Decimal("1.5")


def test_row_average_ignores_empty_cells(teacher, group):
    ann = make_student(teacher, group, "Ann")
    s1 = make_sitting(teacher, group=group, days=0)
    make_sitting(teacher, group=group, days=1)
    s3 = make_sitting(teacher, group=group, days=2)
    make_attempt(s1, ann, 100)
    make_attempt(s3, ann, 50)
    row = build_gradebook(group).rows[0]
    assert row.cells[1] is None
    assert row.average == Decimal("75.0")
    assert row.filled == 2


@pytest.mark.parametrize(
    ("percent", "expected"),
    [("100", "ok"), ("60", "ok"), ("59.9", "warn"), ("40", "warn"), ("39.9", "bad"), ("0", "bad")],
)
def test_bands(percent, expected):
    assert band(Decimal(percent)) == expected


def test_project_filter_keeps_only_that_projects_sessions(teacher, group):
    ann = make_student(teacher, group, "Ann")
    maths = make_project(teacher, "Maths")
    art = make_project(teacher, "Art")
    s_maths = make_sitting(teacher, make_revision(teacher, "M", maths), group=group, days=0)
    s_art = make_sitting(teacher, make_revision(teacher, "A", art), group=group, days=1)
    make_attempt(s_maths, ann, 80)
    make_attempt(s_art, ann, 40)
    assert [c.sitting_id for c in build_gradebook(group, project=maths).columns] == [s_maths.pk]
    book = build_gradebook(group, project=art)
    assert [c.sitting_id for c in book.columns] == [s_art.pk]
    assert book.rows[0].average == Decimal("40.0")
    assert len(build_gradebook(group).columns) == 2


def test_since_filter_by_session_date(teacher, group):
    ann = make_student(teacher, group, "Ann")
    old = make_sitting(teacher, group=group, days=0)
    new = make_sitting(teacher, group=group, days=20)
    make_attempt(old, ann, 10)
    make_attempt(new, ann, 90)
    book = build_gradebook(group, since=date(2026, 9, 10))
    assert [c.sitting_id for c in book.columns] == [new.pk]
    assert book.rows[0].average == Decimal("90.0")
    assert len(build_gradebook(group, since=date(2026, 9, 1)).columns) == 2
    assert len(build_gradebook(group, since=BASE_TIME).columns) == 2


def test_a_teacher_viewer_never_gets_someone_elses_session(
    teacher, other_teacher, admin_user, group
):
    ann = make_student(teacher, group, "Ann")
    mine = make_sitting(teacher, group=group, days=0)
    foreign = make_sitting(other_teacher, days=1, title="Foreign")
    make_attempt(mine, ann, 70)
    make_attempt(foreign, ann, 20)  # an admin linked it across teachers
    assert [c.sitting_id for c in build_gradebook(group, viewer=teacher).columns] == [mine.pk]
    assert len(build_gradebook(group, viewer=admin_user).columns) == 2
    assert len(build_gradebook(group).columns) == 2


def test_query_count_is_constant(teacher, group, django_assert_num_queries):
    students = [make_student(teacher, group, f"Student {i}") for i in range(10)]
    sittings = [make_sitting(teacher, group=group, days=i) for i in range(5)]
    for s in sittings:
        for student in students:
            make_attempt(s, student, 50)
            make_attempt(s, student, 70, pending=1)
    with django_assert_num_queries(3):
        book = build_gradebook(group, viewer=teacher)
    assert len(book.rows) == 10 and len(book.columns) == 5
    # a bigger class must not add queries
    more = [make_student(teacher, group, f"Extra {i}") for i in range(10)]
    extra = make_sitting(teacher, group=group, days=9)
    for student in more:
        make_attempt(extra, student, 33)
    with django_assert_num_queries(3):
        build_gradebook(group, viewer=teacher)


def test_forty_students_by_twenty_sessions_is_fast(teacher, group):
    students = [make_student(teacher, group, f"Student {i:02d}") for i in range(40)]
    sittings = [make_sitting(teacher, group=group, days=i) for i in range(20)]
    Attempt.objects.bulk_create(
        Attempt(**attempt_fields(s, student, 30 + (i * 7 + j * 3) % 70))
        for i, student in enumerate(students)
        for j, s in enumerate(sittings)
    )
    started = perf_counter()
    book = build_gradebook(group, viewer=teacher)
    elapsed = perf_counter() - started
    assert elapsed < 1.0
    assert len(book.rows) == 40 and len(book.columns) == 20
    assert all(c.takers == 40 for c in book.columns)
    assert book.overall_average is not None
