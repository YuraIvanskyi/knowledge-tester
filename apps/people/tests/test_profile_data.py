"""Profile aggregation: what counts, newest first, averages per project, provisional marks."""

from decimal import Decimal

import pytest
from django.utils import translation

from apps.delivery.models import Attempt
from apps.people import profile as data
from apps.people.models import Student

from .profile_factory import (
    make_attempt,
    make_group,
    make_project,
    make_revision,
    make_sitting,
    make_student,
)

pytestmark = pytest.mark.django_db

S = Attempt.Status


@pytest.fixture
def student(teacher):
    return make_student(teacher, group=make_group(teacher))


@pytest.fixture
def math(teacher):
    return make_sitting(make_revision(make_project(teacher, "Математика"), "Дроби"), teacher)


@pytest.fixture
def physics(teacher):
    return make_sitting(
        make_revision(make_project(teacher, "Фізика"), "Рух"), teacher, title="", code="PHYS22"
    )


def test_no_attempts(student):
    profile = data.build_profile(student)
    assert profile.rows == [] and profile.others == [] and profile.projects == []
    assert profile.overall_mean is None and profile.overall_count == 0
    assert not profile.provisional
    assert data.not_counted_text(profile) == ""


def test_counted_rules(student, math):
    make_attempt(math, student, percent="70.0", days=1)
    make_attempt(math, student, percent="90.0", days=2, status=S.AUTO_SUBMITTED)
    make_attempt(math, student, percent="100.0", days=3, status=S.VOIDED)
    make_attempt(math, student, status=S.IN_PROGRESS)
    make_attempt(math, student, days=4, scored=False)  # finished, grading switched off
    profile = data.build_profile(student)

    assert [r.percent for r in profile.rows] == [Decimal("90.0"), Decimal("70.0")]
    assert profile.overall_mean == Decimal("80.0") and profile.overall_count == 2
    assert (profile.in_progress, profile.voided, profile.not_graded) == (1, 1, 1)
    assert {r.kind for r in profile.others} == {data.IN_PROGRESS, data.VOIDED, data.NOT_GRADED}
    assert len(profile.all_rows) == 5
    # the voided 100 % never reaches an average
    assert profile.projects[0].best == Decimal("90.0")


def test_history_is_newest_first_and_carries_the_labels(student, math):
    make_attempt(math, student, percent="50.0", days=1, grade="2")
    make_attempt(math, student, percent="60.0", days=9, grade="3")
    make_attempt(math, student, percent="55.0", days=5, grade="2")
    rows = data.build_profile(student).rows
    assert [r.percent for r in rows] == [Decimal("60.0"), Decimal("55.0"), Decimal("50.0")]
    first = rows[0]
    assert (first.test_title, first.project_title) == ("Дроби", "Математика")
    assert (first.session_title, first.session_code) == ("Контрольна", math.code)
    assert first.grade == "3" and first.score == Decimal("6.00") and not first.provisional


def test_averages_per_project(student, math, physics):
    make_attempt(math, student, percent="70.0", days=1)
    make_attempt(math, student, percent="85.5", days=3)
    make_attempt(math, student, percent="60.0", days=2)
    make_attempt(physics, student, percent="40.0", days=4)
    profile = data.build_profile(student)

    by_title = {p.title: p for p in profile.projects}
    assert list(by_title) == ["Математика", "Фізика"]  # sorted by title
    maths = by_title["Математика"]
    assert maths.count == 3 and maths.mean == Decimal("71.8")  # 215.5 / 3 = 71.83
    assert maths.best == Decimal("85.5") and maths.latest == Decimal("85.5")  # latest = newest
    assert by_title["Фізика"].mean == Decimal("40.0")
    # overall = mean of all four attempts, not of the two project means
    assert profile.overall_count == 4
    assert profile.overall_mean == Decimal("63.9")  # 255.5 / 4 = 63.875


def test_mean_rounds_half_up(student, math):
    make_attempt(math, student, percent="70.0", days=1)
    make_attempt(math, student, percent="70.1", days=2)
    assert data.build_profile(student).overall_mean == Decimal("70.1")  # 70.05 -> 70.1


def test_latest_is_by_date_not_by_creation_order(student, math):
    make_attempt(math, student, percent="90.0", days=10)
    make_attempt(math, student, percent="30.0", days=1)
    assert data.build_profile(student).projects[0].latest == Decimal("90.0")


def test_provisional_marks_rows_projects_and_overall(student, math, physics):
    make_attempt(math, student, percent="70.0", days=1)
    make_attempt(math, student, percent="80.0", days=2, pending=2)
    make_attempt(physics, student, percent="90.0", days=3)
    profile = data.build_profile(student)

    assert profile.provisional and profile.provisional_attempts == 1
    assert [r.provisional for r in profile.rows] == [False, True, False]
    by_title = {p.title: p for p in profile.projects}
    assert by_title["Математика"].provisional and not by_title["Фізика"].provisional


def test_pending_reviews_on_a_voided_attempt_is_not_provisional(student, math):
    make_attempt(math, student, percent="70.0", days=1)
    make_attempt(math, student, percent="10.0", days=2, status=S.VOIDED, pending=3)
    profile = data.build_profile(student)
    assert not profile.provisional and profile.overall_mean == Decimal("70.0")


def test_only_voided_and_in_progress_means_no_average(student, math):
    make_attempt(math, student, status=S.VOIDED)
    make_attempt(math, student, status=S.IN_PROGRESS)
    profile = data.build_profile(student)
    assert profile.rows == [] and profile.projects == [] and profile.overall_mean is None
    assert len(profile.others) == 2


def test_attempt_without_percent_is_listed_but_not_averaged(student, math):
    make_attempt(math, student, percent=None, days=1)  # all questions worth 0 points
    make_attempt(math, student, percent="60.0", days=2)
    profile = data.build_profile(student)
    assert len(profile.rows) == 2
    assert profile.overall_count == 1 and profile.overall_mean == Decimal("60.0")
    assert profile.projects[0].count == 1


def test_other_students_attempts_are_not_included(teacher, student, math):
    other = make_student(teacher, "Коваль Олена")
    make_attempt(math, student, percent="70.0")
    make_attempt(math, other, percent="10.0")
    make_attempt(math, None, percent="20.0")
    assert [r.percent for r in data.build_profile(student).rows] == [Decimal("70.0")]


def test_foreign_session_is_hidden_from_the_owner_but_not_from_an_admin(
    teacher, other_teacher, admin_user, student
):
    foreign = make_sitting(
        make_revision(make_project(other_teacher, "Чуже"), "Секрет"), other_teacher
    )
    own = make_sitting(make_revision(make_project(teacher)), teacher)
    make_attempt(own, student, percent="70.0")
    make_attempt(foreign, student, percent="50.0")  # e.g. linked by an admin across teachers

    assert [r.test_title for r in data.build_profile(student).rows] == ["Дроби"]
    assert [r.test_title for r in data.build_profile(student, viewer=teacher).rows] == ["Дроби"]
    seen = data.build_profile(student, viewer=admin_user)
    assert sorted(r.test_title for r in seen.rows) == ["Дроби", "Секрет"]


def test_session_without_a_title_has_only_its_code(student, physics):
    make_attempt(physics, student)
    row = data.build_profile(student).rows[0]
    assert row.session_title == "" and row.session_code == "PHYS22"


def test_few_queries_whatever_the_number_of_attempts(
    student, math, physics, django_assert_max_num_queries
):
    for day in range(12):
        make_attempt(math if day % 2 else physics, student, percent="75.0", days=day)
    with django_assert_max_num_queries(2):
        profile = data.build_profile(student)
        assert len(profile.rows) == 12
        assert profile.rows[0].test_title and profile.rows[0].project_title


def test_not_counted_text_counts_each_kind(student, math):
    make_attempt(math, student, status=S.IN_PROGRESS)
    make_attempt(math, student, status=S.VOIDED)
    make_attempt(math, student, status=S.VOIDED)
    make_attempt(math, student, scored=False)
    with translation.override("en"):
        text = data.not_counted_text(data.build_profile(student))
    assert text == (
        "Not counted: 1 attempt in progress; 2 voided attempts; 1 attempt without a score"
    )


# --- small helpers --------------------------------------------------------------------------


@pytest.mark.parametrize("bad", ["=1+1", "+1", "-1", "@SUM(A1)", "\tx", "\rx"])
def test_csv_safe_prefixes_dangerous_cells(bad):
    assert data.csv_safe(bad) == "'" + bad


def test_csv_safe_leaves_normal_text_and_none():
    assert data.csv_safe("Іван") == "Іван"
    assert data.csv_safe(None) == ""
    assert data.csv_safe("a=b") == "a=b"
    assert data.csv_safe(12) == "12"


def test_download_name_keeps_cyrillic_and_has_a_fallback(teacher):
    assert data.download_name(make_student(teacher, "Іваненко Дем’ян"), "csv") == (
        "іваненко-демян_results.csv"
    )
    odd = make_student(teacher, "???")
    assert data.download_name(odd, "pdf") == f"student-{odd.pk}_results.pdf"
    assert len(data.download_name(make_student(teacher, "Я" * 200), "pdf")) < 100


def test_normalize_text_unifies_line_breaks():
    assert data.normalize_text("a\r\nb\rc\nd") == "a\nb\nc\nd"
    assert data.normalize_text(None) == ""


# --- deleting -------------------------------------------------------------------------------


def test_delete_student_keeping_results_unlinks_the_attempts(student, math):
    first = make_attempt(math, student, percent="70.0")
    second = make_attempt(math, student, status=S.IN_PROGRESS)
    pk = student.pk
    outcome = data.delete_student(student, False)

    assert (outcome.deleted_attempts, outcome.unlinked_attempts) == (0, 2)
    assert not Student.objects.filter(pk=pk).exists()
    for attempt in (first, second):
        attempt.refresh_from_db()
        assert attempt.student_id is None and attempt.taker == {"name": "typed name"}


def test_delete_student_and_attempts_removes_the_attempts_and_their_answers(student, math):
    from apps.delivery.models import Answer

    attempt = make_attempt(math, student)
    Answer.objects.create(attempt=attempt, question_key="q1", value="x")
    bystander = make_attempt(math, None, percent="10.0")
    outcome = data.delete_student(student, True)

    assert (outcome.deleted_attempts, outcome.unlinked_attempts) == (1, 0)
    assert not Attempt.objects.filter(pk=attempt.pk).exists()
    assert not Answer.objects.filter(attempt_id=attempt.pk).exists()
    assert Attempt.objects.filter(pk=bystander.pk).exists()


def test_delete_with_attempts_never_deletes_another_teachers_session(
    teacher, other_teacher, student, math
):
    foreign = make_sitting(make_revision(make_project(other_teacher)), other_teacher)
    mine = make_attempt(math, student)
    theirs = make_attempt(foreign, student)
    outcome = data.delete_student(student, True, viewer=teacher)

    assert (outcome.deleted_attempts, outcome.unlinked_attempts) == (1, 1)
    assert not Attempt.objects.filter(pk=mine.pk).exists()
    theirs.refresh_from_db()
    assert theirs.student_id is None


def test_admin_delete_removes_every_linked_attempt(
    admin_user, teacher, other_teacher, student, math
):
    foreign = make_sitting(make_revision(make_project(other_teacher)), other_teacher)
    make_attempt(math, student)
    make_attempt(foreign, student)
    outcome = data.delete_student(student, True, viewer=admin_user)
    assert outcome.deleted_attempts == 2 and Attempt.objects.count() == 0


def test_link_counts(teacher, other_teacher, student, math):
    foreign = make_sitting(make_revision(make_project(other_teacher)), other_teacher)
    make_attempt(math, student)
    make_attempt(math, student, status=S.VOIDED)
    make_attempt(foreign, student)
    counts = data.link_counts(student, teacher)
    assert (counts.linked, counts.removable) == (3, 2)
