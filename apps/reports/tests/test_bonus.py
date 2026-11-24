"""Extra points for the whole work, with the reason: grading, the attempt sheet, results, CSV, PDF
and the student's result page."""

import csv
import io
from decimal import Decimal as D

import pytest
from django.urls import reverse
from pypdf import PdfReader

from apps.delivery.models import Answer, Attempt
from apps.grading.engine import grade_test
from apps.grading.service import grade_attempt

from .test_views import DOC, login, make_attempt, other_teacher, sitting, teacher  # noqa: F401

pytestmark = pytest.mark.django_db


def sheet_url(attempt):
    return reverse("reports:attempt", args=[attempt.pk])


def post_bonus(client, attempt, points, note="", **extra):
    return client.post(
        sheet_url(attempt), {"bonus_points": points, "bonus_note": note, "action": "save", **extra}
    )


# --- grading ------------------------------------------------------------------------------------


def test_engine_adds_the_bonus_and_keeps_the_total_inside_the_scale():
    test = DOC["test"]
    answers = {"q1": ["a"], "q2": ["a"]}  # 1 + 1 of 6, q3 needs review
    assert grade_test(test, answers).score == D("2.00")
    assert grade_test(test, answers, bonus=D("1.5")).score == D("3.50")
    assert grade_test(test, answers, bonus=D("-1")).score == D("1.00")
    assert grade_test(test, answers, bonus=D("10")).score == D("6.00")  # not above the maximum
    assert grade_test(test, answers, bonus=D("-10")).score == D("0.00")  # not below 0
    capped = grade_test(test, answers, bonus=D("10"))
    assert capped.percent == D("100.0") and capped.max_score == D("6.00")


def test_regrading_keeps_the_bonus(sitting):  # noqa: F811
    attempt = make_attempt(sitting, "Ivan", {"q1": ["a"], "q3": "text"})
    Attempt.objects.filter(pk=attempt.pk).update(bonus_points=D("2"))
    attempt.refresh_from_db()
    grade_attempt(attempt)
    assert attempt.score == D("3.00")
    # a reviewer's points for the open answer come on top
    Answer.objects.filter(attempt=attempt, question_key="q3").update(manual_score=D("1"))
    grade_attempt(attempt)
    attempt.refresh_from_db()
    assert attempt.score == D("4.00") and attempt.pending_reviews == 0


# --- the attempt sheet --------------------------------------------------------------------------


def test_teacher_gives_extra_points_with_a_reason(login, sitting):  # noqa: F811
    attempt = make_attempt(sitting, "Ivan", {"q1": ["a"]})  # 1 of 6
    page = login.get(sheet_url(attempt)).content.decode()
    assert 'name="bonus_points"' in page and 'name="bonus_note"' in page
    assert 'min="-6" max="6" step="0.5"' in page

    r = post_bonus(login, attempt, "2,5", "  extra   task  ")
    assert r.status_code == 302
    attempt.refresh_from_db()
    assert attempt.bonus_points == D("2.50") and attempt.bonus_note == "extra task"
    assert attempt.score == D("3.50") and attempt.percent == D("58.3")

    page = login.get(r["Location"]).content.decode()
    assert "Extra points saved." in page
    assert "+2.5" in page and "extra task" in page and "included in the score" in page


def test_a_reason_is_required_and_input_is_kept(login, sitting):  # noqa: F811
    attempt = make_attempt(sitting, "Ivan", {"q1": ["a"]})
    r = post_bonus(login, attempt, "2", "")
    assert r.status_code == 200
    page = r.content.decode()
    assert "Write what the extra points are for." in page
    assert 'value="2"' in page and 'aria-invalid="true"' in page
    attempt.refresh_from_db()
    assert attempt.bonus_points == 0 and attempt.score == D("1.00")


@pytest.mark.parametrize("raw", ["0.3", "7", "-6.5", "abc", "nan", "1e3"])
def test_bad_points_are_refused(login, sitting, raw):  # noqa: F811
    attempt = make_attempt(sitting, "Ivan", {"q1": ["a"]})
    r = post_bonus(login, attempt, raw, "why")
    assert r.status_code == 200
    assert "Enter extra points from -6 to 6 in steps of 0.5." in r.content.decode()
    attempt.refresh_from_db()
    assert attempt.bonus_points == 0


def test_a_deduction_and_clearing_it(login, sitting):  # noqa: F811
    attempt = make_attempt(sitting, "Ivan", {"q1": ["a"], "q2": ["a", "b"]})  # 3 of 6
    post_bonus(login, attempt, "−1", "used a phone")  # a typed minus sign
    attempt.refresh_from_db()
    assert attempt.bonus_points == D("-1.00") and attempt.score == D("2.00")
    assert "−1" in login.get(sheet_url(attempt)).content.decode()
    post_bonus(login, attempt, "", "used a phone")  # empty = none; the reason goes with it
    attempt.refresh_from_db()
    assert attempt.bonus_points == 0 and attempt.bonus_note == "" and attempt.score == D("3.00")


def test_capped_total_is_explained(login, sitting):  # noqa: F811
    attempt = make_attempt(sitting, "Ivan", {"q1": ["a"], "q2": ["a", "b"]})  # 3 of 6
    post_bonus(login, attempt, "5", "olympiad")
    attempt.refresh_from_db()
    assert attempt.score == D("6.00")
    page = login.get(sheet_url(attempt)).content.decode()
    assert "which stays within 0 to 6" in page


def test_saved_with_the_review_in_one_go(login, sitting):  # noqa: F811
    attempt = make_attempt(sitting, "Ivan", {"q1": ["a"], "q3": "Common denominator"})
    r = post_bonus(login, attempt, "1", "neat work", points_q3="2", comment_q3="good")
    assert r.status_code == 302
    attempt.refresh_from_db()
    assert attempt.score == D("4.00") and attempt.pending_reviews == 0


def test_unchanged_fields_change_nothing(login, sitting):  # noqa: F811
    attempt = make_attempt(sitting, "Ivan", {"q1": ["a"]})
    r = post_bonus(login, attempt, "", "")
    page = login.get(r["Location"]).content.decode()
    assert "Nothing to save" in page and "Extra points saved." not in page


@pytest.mark.parametrize("status", [Attempt.Status.IN_PROGRESS, Attempt.Status.VOIDED])
def test_only_finished_work_gets_extra_points(login, sitting, status):  # noqa: F811
    attempt = make_attempt(sitting, "Ivan", {"q1": ["a"]})
    Attempt.objects.filter(pk=attempt.pk).update(status=status)
    assert 'name="bonus_points"' not in login.get(sheet_url(attempt)).content.decode()
    post_bonus(login, attempt, "2", "why")
    attempt.refresh_from_db()
    assert attempt.bonus_points == 0


def test_not_offered_when_grading_is_off(login, teacher):  # noqa: F811
    from apps.assessments.models import Assessment, Project, Revision
    from apps.delivery.models import Sitting

    doc = {**DOC, "test": {**DOC["test"], "grading": {"enabled": False}}}
    project = Project.objects.create(owner=teacher, title="P2")
    assessment = Assessment.objects.create(project=project, title="Q", document=doc)
    revision = Revision.objects.create(assessment=assessment, number=1, document=doc)
    ungraded = Sitting.objects.create(revision=revision, code="XYZ234", created_by=teacher)
    attempt = make_attempt(ungraded, "Ivan", {"q1": ["a"]})
    assert 'name="bonus_points"' not in login.get(sheet_url(attempt)).content.decode()


def test_another_teacher_cannot_give_points(client, other_teacher, sitting):  # noqa: F811
    attempt = make_attempt(sitting, "Ivan", {"q1": ["a"]})
    client.force_login(other_teacher)
    assert post_bonus(client, attempt, "2", "why").status_code == 404
    attempt.refresh_from_db()
    assert attempt.bonus_points == 0


# --- everywhere else the result shows -----------------------------------------------------------


def give(attempt, points, note):
    Attempt.objects.filter(pk=attempt.pk).update(bonus_points=D(points), bonus_note=note)
    attempt.refresh_from_db()
    grade_attempt(attempt)
    attempt.refresh_from_db()
    return attempt


def test_results_table_marks_the_extra_points(login, sitting):  # noqa: F811
    give(make_attempt(sitting, "Ivan", {"q1": ["a"]}), "2", "extra task")
    html = login.get(reverse("reports:session", args=[sitting.pk])).content.decode()
    assert "3 / 6" in html and "(+2)" in html and "extra task" in html


def test_csv_has_extra_points_and_reason(login, sitting):  # noqa: F811
    give(make_attempt(sitting, "Ivan", {"q1": ["a"]}), "-1.5", "late")
    make_attempt(sitting, "Olena", {"q1": ["a"]})
    body = login.get(reverse("reports:csv", args=[sitting.pk])).content.decode("utf-8-sig")
    rows = list(csv.reader(io.StringIO(body)))
    header = rows[0]
    at = header.index("Pending reviews")
    assert header[at + 1 : at + 3] == ["Extra points", "What for"]
    by_name = {r[0]: dict(zip(header, r, strict=True)) for r in rows[1:]}
    assert (by_name["Ivan"]["Extra points"], by_name["Ivan"]["What for"]) == ("-1.50", "late")
    assert (by_name["Olena"]["Extra points"], by_name["Olena"]["What for"]) == ("", "")


def test_csv_reason_is_formula_safe(login, sitting):  # noqa: F811
    give(make_attempt(sitting, "Ivan", {"q1": ["a"]}), "1", "=HYPERLINK(1)")
    body = login.get(reverse("reports:csv", args=[sitting.pk])).content.decode("utf-8-sig")
    assert "'=HYPERLINK(1)" in body


def test_pdf_sheet_names_the_extra_points(login, sitting):  # noqa: F811
    attempt = give(make_attempt(sitting, "Ivan", {"q1": ["a"]}), "2", "extra task")
    Attempt.objects.filter(pk=attempt.pk).update(away_count=3, away_seconds=80)
    response = login.get(reverse("reports:attempt_pdf", args=[attempt.pk]))
    text = "\n".join(page.extract_text() for page in PdfReader(io.BytesIO(response.content)).pages)
    assert "Extra points: +2 · extra task" in text
    assert "Left the test page: 3 times (1 min 20 s)" in text


def test_student_sees_the_extra_points(client, sitting):  # noqa: F811
    attempt = give(make_attempt(sitting, "Ivan", {"q1": ["a"]}), "2", "extra task")
    client.cookies[f"kt_attempt_{sitting.code}"] = str(attempt.token)
    page = client.get(f"/s/{sitting.code}/done/").content.decode()
    assert "Extra points from your teacher" in page and "+2" in page and "extra task" in page
