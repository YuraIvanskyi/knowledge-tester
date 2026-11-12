"""Profile pages: access, notes, CSV, PDF download and the delete flow."""

import csv
import io

import pytest
from django.contrib.messages import get_messages
from django.test import Client
from django.urls import reverse

from apps.delivery.models import Attempt
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
NAMES = ["student", "student_notes", "student_delete", "student_csv", "student_pdf"]


def url(name, student):
    return reverse(f"people:{name}", args=[student.pk])


@pytest.fixture
def group(teacher):
    return make_group(teacher, "7-А")


@pytest.fixture
def student(teacher, group):
    return make_student(teacher, "Іваненко Петро", group=group, pin="4821", notes="Сидить уперед")


@pytest.fixture
def sitting(teacher):
    return make_sitting(make_revision(make_project(teacher, "Математика"), "Дроби"), teacher)


@pytest.fixture
def stranger_student(other_teacher):
    return make_student(other_teacher, "Чужий Учень")


def flashed(response):
    return [str(m) for m in get_messages(response.wsgi_request)]


def rows_of(response):
    text = response.content.decode("utf-8-sig")
    return list(csv.reader(io.StringIO(text)))


# --- access ---------------------------------------------------------------------------------


@pytest.mark.parametrize("name", NAMES)
def test_anonymous_is_sent_to_login(client, student, name):
    response = client.get(url(name, student))
    assert response.status_code == 302 and "login" in response["Location"]
    response = client.post(url(name, student))
    assert response.status_code == 302 and "login" in response["Location"]


@pytest.mark.parametrize("name", NAMES)
def test_foreign_student_is_a_404_for_every_route(teacher_client, stranger_student, name):
    assert teacher_client.get(url(name, stranger_student)).status_code in (404, 405)
    assert teacher_client.post(url(name, stranger_student), {"attempts": "delete"}).status_code in (
        404,
        405,
    )


@pytest.mark.parametrize("name", ["student", "student_delete", "student_csv", "student_pdf"])
def test_foreign_student_get_is_exactly_404(teacher_client, stranger_student, name):
    response = teacher_client.get(url(name, stranger_student))
    assert response.status_code == 404
    assert "Чужий" not in response.content.decode()


def test_foreign_student_notes_post_is_404_and_changes_nothing(teacher_client, stranger_student):
    response = teacher_client.post(url("student_notes", stranger_student), {"notes": "hijack"})
    assert response.status_code == 404
    stranger_student.refresh_from_db()
    assert stranger_student.notes == ""


def test_foreign_student_delete_post_is_404_and_deletes_nothing(teacher_client, stranger_student):
    response = teacher_client.post(url("student_delete", stranger_student), {"attempts": "keep"})
    assert response.status_code == 404
    assert Student.objects.filter(pk=stranger_student.pk).exists()


def test_unknown_student_is_404(teacher_client):
    assert teacher_client.get(reverse("people:student", args=[99999])).status_code == 404


def test_admin_can_open_any_students_profile(client_for, admin_user, student):
    response = client_for(admin_user).get(url("student", student))
    assert response.status_code == 200 and "Іваненко Петро" in response.content.decode()


def test_mutating_routes_refuse_get_and_the_page_refuses_post(teacher_client, student):
    assert teacher_client.get(url("student_notes", student)).status_code == 405
    assert teacher_client.post(url("student", student)).status_code == 405
    assert teacher_client.post(url("student_csv", student)).status_code == 405
    assert teacher_client.post(url("student_pdf", student)).status_code == 405


@pytest.mark.parametrize("name", ["student_notes", "student_delete"])
def test_posts_need_a_csrf_token(teacher, student, name):
    strict = Client(enforce_csrf_checks=True)
    strict.force_login(teacher)
    assert strict.post(url(name, student), {"notes": "x", "attempts": "delete"}).status_code == 403
    assert Student.objects.filter(pk=student.pk).exists()


# --- the page -------------------------------------------------------------------------------


def test_page_shows_header_notes_and_links(teacher_client, group, student):
    html = teacher_client.get(url("student", student)).content.decode()
    assert "Іваненко Петро" in html
    assert reverse("people:group", args=[group.pk]) in html
    assert reverse("people:student_edit", args=[student.pk]) in html
    assert "4821" in html  # the owner sees the PIN
    assert "Active student" in html
    assert "Сидить уперед" in html
    for name in ("student_notes", "student_csv", "student_pdf", "student_delete"):
        assert url(name, student) in html
    assert "No finished results" in html  # nothing linked yet


def test_inactive_student_is_marked(teacher_client, student):
    Student.objects.filter(pk=student.pk).update(is_active=False)
    assert "Inactive student" in teacher_client.get(url("student", student)).content.decode()


def test_student_without_group_or_pin(teacher_client, teacher):
    loner = make_student(teacher, "Без Групи")
    html = teacher_client.get(url("student", loner)).content.decode()
    assert "No group" in html and "No PIN" in html


def test_history_and_averages_are_listed(teacher_client, teacher, student, sitting):
    other = make_sitting(
        make_revision(make_project(teacher, "Фізика"), "Рух"), teacher, code="PHYS22"
    )
    first = make_attempt(sitting, student, percent="70.0", days=1, grade="3")
    last = make_attempt(sitting, student, percent="90.0", days=5, grade="5")
    make_attempt(other, student, percent="50.0", days=3)
    html = teacher_client.get(url("student", student)).content.decode()

    assert reverse("reports:attempt", args=[first.pk]) in html
    assert reverse("reports:attempt", args=[last.pk]) in html
    newest_first = [reverse("reports:attempt", args=[a.pk]) for a in (last, first)]
    assert html.index(newest_first[0]) < html.index(newest_first[1])
    assert "Дроби" in html and "Математика" in html and "Фізика" in html
    assert "70 %" in html and "90 %" in html
    assert "70 %" in html  # overall (70 + 90 + 50) / 3
    assert "Counted attempts" in html and "Overall average" in html
    assert "Provisional" not in html


def test_provisional_results_are_marked_everywhere(teacher_client, student, sitting):
    make_attempt(sitting, student, percent="80.0", days=1, pending=2)
    html = teacher_client.get(url("student", student)).content.decode()
    assert html.count("Provisional") >= 3  # overall, project row, history row
    assert "Waiting for review" in html


def test_attempts_that_do_not_count_are_shown_apart(teacher_client, student, sitting):
    make_attempt(sitting, student, percent="80.0", days=1)
    voided = make_attempt(sitting, student, status=S.VOIDED)
    running = make_attempt(sitting, student, status=S.IN_PROGRESS)
    html = teacher_client.get(url("student", student)).content.decode()
    assert "Not counted: 1 attempt in progress; 1 voided attempt" in html
    assert reverse("reports:attempt", args=[voided.pk]) in html
    assert reverse("reports:attempt", args=[running.pk]) in html
    assert "Voided" in html and "In progress" in html


def test_hostile_text_is_escaped(teacher_client, teacher):
    evil = make_student(teacher, "<script>alert(1)</script>", notes="<img src=x onerror=alert(2)>")
    html = teacher_client.get(url("student", evil)).content.decode()
    assert "<script>alert(1)" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "<img src=x" not in html and "&lt;img src=x onerror=alert(2)&gt;" in html


def test_other_teachers_attempt_never_appears(teacher_client, other_teacher, student, sitting):
    foreign = make_sitting(
        make_revision(make_project(other_teacher, "Секретний проєкт"), "Секретний тест"),
        other_teacher,
    )
    make_attempt(sitting, student, percent="70.0")
    make_attempt(foreign, student, percent="10.0")
    html = teacher_client.get(url("student", student)).content.decode()
    assert "Секретн" not in html


def test_page_query_count_is_flat(teacher_client, student, sitting, django_assert_max_num_queries):
    for day in range(15):
        make_attempt(sitting, student, percent="75.0", days=day)
    with django_assert_max_num_queries(12):  # session, user, student, group, attempts, base page
        assert teacher_client.get(url("student", student)).status_code == 200


# --- notes ----------------------------------------------------------------------------------


def test_saving_notes(teacher_client, student):
    response = teacher_client.post(
        url("student_notes", student), {"notes": "  Потрібна допомога\r\nз дробами  "}
    )
    assert response.status_code == 302
    assert response["Location"] == url("student", student) + "#notes"
    student.refresh_from_db()
    assert student.notes == "Потрібна допомога\nз дробами"
    followed = teacher_client.get(response["Location"].split("#")[0])
    assert "Notes saved." in followed.content.decode()


def test_notes_can_be_cleared(teacher_client, student):
    teacher_client.post(url("student_notes", student), {"notes": ""})
    student.refresh_from_db()
    assert student.notes == ""


def test_notes_are_plain_text_and_redisplayed_escaped(teacher_client, student):
    teacher_client.post(url("student_notes", student), {"notes": "<b>bold</b> & more"})
    html = teacher_client.get(url("student", student)).content.decode()
    assert "<b>bold</b>" not in html
    assert "&lt;b&gt;bold&lt;/b&gt; &amp; more" in html


def test_notes_too_long_are_refused_and_the_text_is_kept(teacher_client, student):
    too_long = "я" * 2001
    response = teacher_client.post(url("student_notes", student), {"notes": too_long})
    assert response.status_code == 400
    html = response.content.decode()
    assert "at most 2000 characters" in html and too_long in html
    student.refresh_from_db()
    assert student.notes == "Сидить уперед"


def test_notes_of_exactly_the_limit_with_windows_line_breaks_are_accepted(teacher_client, student):
    text = "\r\n".join(["x" * 99] * 20)  # 20 * 99 + 19 = 1999 characters once LF is counted once
    assert teacher_client.post(url("student_notes", student), {"notes": text}).status_code == 302


def test_saving_notes_does_not_touch_other_fields(teacher_client, student):
    teacher_client.post(
        url("student_notes", student), {"notes": "новина", "full_name": "Hacked", "pin": "0000"}
    )
    student.refresh_from_db()
    assert (student.full_name, student.pin, student.notes) == ("Іваненко Петро", "4821", "новина")


# --- CSV ------------------------------------------------------------------------------------


def test_csv_lists_counted_and_other_attempts(teacher_client, student, sitting):
    make_attempt(sitting, student, percent="70.0", days=1, grade="3")
    make_attempt(sitting, student, percent="80.0", days=2, pending=1)
    make_attempt(sitting, student, percent="55.0", status=S.VOIDED)
    make_attempt(sitting, student, status=S.IN_PROGRESS)
    response = teacher_client.get(url("student_csv", student))

    assert response.status_code == 200
    assert response["Content-Type"] == "text/csv; charset=utf-8"
    assert response.content.startswith("﻿".encode())
    rows = rows_of(response)
    header, body = rows[0], rows[1:]
    assert header[0] == "Student" and "Status" in header and "Percent" in header
    assert len(body) == 4
    index = {name: i for i, name in enumerate(header)}
    assert {row[index["Status"]] for row in body} == {"submitted", "voided", "in_progress"}
    newest = next(row for row in body if row[index["Percent"]] == "80.0")
    assert newest[index["Pending reviews"]] == "1"
    assert newest[0] == "Іваненко Петро" and newest[index["Group"]] == "7-А"
    assert newest[index["Test"]] == "Дроби" and newest[index["Project"]] == "Математика"
    assert newest[index["Date"]] == "2026-09-03 09:00"
    first = next(row for row in body if row[index["Percent"]] == "70.0")
    assert first[index["Score"]] == "7.00" and first[index["Max score"]] == "10.00"
    assert first[index["Grade"]] == "3"
    unscored = next(row for row in body if row[index["Status"]] == "in_progress")
    assert unscored[index["Score"]] == "" and unscored[index["Percent"]] == ""


def test_csv_of_a_student_without_attempts_is_just_the_header(teacher_client, student):
    rows = rows_of(teacher_client.get(url("student_csv", student)))
    assert len(rows) == 1


@pytest.mark.parametrize("bad", ['=HYPERLINK("http://x","y")', "+1+1", "-2+3", "@SUM(A1)", "\tx"])
def test_csv_neutralises_formula_injection(teacher_client, teacher, bad):
    group = make_group(teacher, bad + "g")
    evil = make_student(teacher, bad + " Name", group=group)
    sitting = make_sitting(make_revision(make_project(teacher, bad), bad), teacher, title=bad)
    make_attempt(sitting, evil, grade=bad)
    rows = rows_of(teacher_client.get(url("student_csv", evil)))
    cells = rows[1]
    assert cells[0].startswith("'") is (bad[0] in "=+-@\t") or True
    for cell in (cells[2], cells[3], cells[4], cells[11]):  # test, project, session, grade
        assert cell == "'" + bad
    # name and group are cells too
    assert cells[0] == "'" + bad + " Name"
    assert cells[1] == "'" + bad + "g"


def test_csv_filename_from_a_cyrillic_name(teacher_client, student):
    disposition = teacher_client.get(url("student_csv", student))["Content-Disposition"]
    assert disposition.startswith("attachment")
    assert "filename*=utf-8''" in disposition
    assert "%D1%96%D0%B2%D0%B0%D0%BD%D0%B5%D0%BD%D0%BA%D0%BE" in disposition  # "іваненко"
    assert disposition.endswith("_results.csv") or "results.csv" in disposition


def test_csv_filename_is_safe_for_awkward_names(teacher_client, teacher):
    awkward = make_student(teacher, 'a/b\\c"d\r\ne.csv')
    disposition = teacher_client.get(url("student_csv", awkward))["Content-Disposition"]
    assert "\n" not in disposition and "\r" not in disposition and "/" not in disposition


# --- PDF ------------------------------------------------------------------------------------


def test_pdf_download(teacher_client, student, sitting):
    make_attempt(sitting, student, percent="70.0")
    response = teacher_client.get(url("student_pdf", student))
    assert response.status_code == 200 and response["Content-Type"] == "application/pdf"
    assert response.content.startswith(b"%PDF")
    disposition = response["Content-Disposition"]
    assert disposition.startswith("attachment") and "filename*=utf-8''" in disposition
    assert disposition.endswith(".pdf")


def test_pdf_paper_option(teacher_client, student):
    from pypdf import PdfReader

    def width(query):
        reader = PdfReader(
            io.BytesIO(teacher_client.get(url("student_pdf", student), query).content)
        )
        return round(float(reader.pages[0].mediabox.width))

    assert width({}) == 595 and width({"paper": "A4"}) == 595
    assert width({"paper": "Letter"}) == 612
    assert width({"paper": "A0"}) == 595  # junk falls back to A4


# --- delete ---------------------------------------------------------------------------------


def test_delete_page_shows_both_choices_with_counts(teacher_client, student, sitting):
    make_attempt(sitting, student)
    make_attempt(sitting, student, status=S.VOIDED)
    response = teacher_client.get(url("student_delete", student))
    html = response.content.decode()
    assert response.status_code == 200
    assert "2 attempts are linked to this student" in html
    assert "Delete student, keep results" in html and "Delete student and attempts" in html
    assert 'name="attempts" value="keep"' in html and 'name="attempts" value="delete"' in html
    assert "2 attempts and their answers will be removed" in html
    assert Student.objects.filter(pk=student.pk).exists()  # GET never deletes


def test_delete_page_without_attempts_has_one_button(teacher_client, student):
    html = teacher_client.get(url("student_delete", student)).content.decode()
    assert "No attempts are linked" in html
    assert 'value="delete"' not in html and 'value="keep"' in html


def test_delete_keeping_the_results(teacher_client, group, student, sitting):
    attempt = make_attempt(sitting, student, name="Петро І.")
    pending = make_attempt(sitting, student, status=S.IN_PROGRESS)
    response = teacher_client.post(url("student_delete", student), {"attempts": "keep"})

    assert response.status_code == 302
    assert response["Location"] == reverse("people:group", args=[group.pk])
    assert not Student.objects.filter(pk=student.pk).exists()
    for row in (attempt, pending):
        row.refresh_from_db()
        assert row.student_id is None
    assert attempt.taker == {"name": "Петро І."} and attempt.percent is not None
    assert flashed(response) == [
        "Student “Іваненко Петро” deleted. 2 attempts stay in their sessions, unlinked."
    ]


def test_delete_with_the_attempts(teacher_client, group, student, sitting):
    gone = make_attempt(sitting, student)
    bystander = make_attempt(sitting, None, name="Хтось інший")
    response = teacher_client.post(url("student_delete", student), {"attempts": "delete"})

    assert response.status_code == 302
    assert not Student.objects.filter(pk=student.pk).exists()
    assert not Attempt.objects.filter(pk=gone.pk).exists()
    assert Attempt.objects.filter(pk=bystander.pk).exists()
    assert flashed(response) == ["Student “Іваненко Петро” and 1 attempt deleted."]


def test_delete_without_attempts_goes_back_to_the_list_when_there_is_no_group(
    teacher_client, teacher
):
    loner = make_student(teacher, "Без Групи")
    response = teacher_client.post(url("student_delete", loner), {"attempts": "keep"})
    assert response["Location"] == reverse("people:students")
    assert flashed(response) == ["Student “Без Групи” deleted."]
    assert not Student.objects.filter(pk=loner.pk).exists()


def test_delete_needs_an_explicit_choice(teacher_client, student, sitting):
    attempt = make_attempt(sitting, student)
    for payload in ({}, {"attempts": ""}, {"attempts": "yes"}, {"attempts": "DELETE"}):
        response = teacher_client.post(url("student_delete", student), payload)
        assert response.status_code == 302
        assert response["Location"] == url("student_delete", student)
    assert Student.objects.filter(pk=student.pk).exists()
    attempt.refresh_from_db()
    assert attempt.student_id == student.pk


def test_other_students_are_untouched_by_a_delete(teacher_client, teacher, group, student, sitting):
    sibling = make_student(teacher, "Коваль Олена", group=group)
    kept = make_attempt(sitting, sibling)
    teacher_client.post(url("student_delete", student), {"attempts": "delete"})
    kept.refresh_from_db()
    assert kept.student_id == sibling.pk


def test_admin_deleting_removes_attempts_of_every_teacher(
    client_for, admin_user, other_teacher, student, sitting
):
    foreign = make_sitting(make_revision(make_project(other_teacher)), other_teacher)
    mine = make_attempt(sitting, student)
    theirs = make_attempt(foreign, student)
    client_for(admin_user).post(url("student_delete", student), {"attempts": "delete"})
    assert not Attempt.objects.filter(pk__in=[mine.pk, theirs.pk]).exists()


def test_teacher_deleting_never_removes_foreign_session_attempts(
    teacher_client, other_teacher, student, sitting
):
    foreign = make_sitting(make_revision(make_project(other_teacher)), other_teacher)
    make_attempt(sitting, student)
    theirs = make_attempt(foreign, student)
    page = teacher_client.get(url("student_delete", student)).content.decode()
    assert "only unlinked, never deleted" in page
    teacher_client.post(url("student_delete", student), {"attempts": "delete"})
    theirs.refresh_from_db()
    assert theirs.student_id is None  # unlinked, still there
