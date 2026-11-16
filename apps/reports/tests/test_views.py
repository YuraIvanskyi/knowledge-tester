import csv
import io
from decimal import Decimal as D

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from apps.assessments.models import Assessment, Project, Revision
from apps.delivery.models import Answer, Attempt, Sitting
from apps.grading.service import grade_attempt

pytestmark = pytest.mark.django_db

DOC = {
    "format": "knowledge-tester/test",
    "version": 1,
    "test": {
        "title": "Mixed quiz",
        "taker_fields": [
            {"key": "name", "label": "Full name", "required": True},
            {"key": "class", "label": "Class", "required": False},
        ],
        "grading": {"enabled": True, "scale": "percent"},
        "questions": [
            {
                "id": "q1",
                "type": "single_choice",
                "text": "Capital of Ukraine?",
                "points": 1,
                "options": [
                    {"id": "a", "text": "Kyiv", "correct": True},
                    {"id": "b", "text": "Lviv"},
                    {"id": "c", "text": "Odesa"},
                ],
            },
            {
                "id": "q2",
                "type": "multiple_choice",
                "text": "Pick primes",
                "points": 2,
                "options": [
                    {"id": "a", "text": "two", "correct": True},
                    {"id": "b", "text": "three", "correct": True},
                    {"id": "c", "text": "four"},
                    {"id": "d", "text": "six"},
                ],
            },
            {
                "id": "q3",
                "type": "open",
                "text": "Explain fractions",
                "points": 3,
                "rubric": "Mention denominators",
            },
        ],
    },
}


@pytest.fixture
def teacher():
    return get_user_model().objects.create_user("teacher", password="pw")


@pytest.fixture
def other_teacher():
    return get_user_model().objects.create_user("other", password="pw")


@pytest.fixture
def sitting(teacher):
    project = Project.objects.create(owner=teacher, title="P")
    assessment = Assessment.objects.create(project=project, title="Quiz", document=DOC)
    revision = Revision.objects.create(
        assessment=assessment, number=1, document=DOC, content_hash="h"
    )
    return Sitting.objects.create(revision=revision, code="ABC234", created_by=teacher)


def make_attempt(sitting, name, answers, order=None, status=Attempt.Status.SUBMITTED):
    attempt = Attempt.objects.create(
        sitting=sitting,
        taker={"name": name, "class": "7-A"},
        status=status,
        question_order=order or [],
    )
    for key, value in answers.items():
        Answer.objects.create(attempt=attempt, question_key=key, value=value)
    if status != Attempt.Status.IN_PROGRESS:
        grade_attempt(attempt)
        attempt.refresh_from_db()
    return attempt


@pytest.fixture
def attempts(sitting):
    # ivan: 1 + 2 + pending open = 3 of 6, provisional
    ivan = make_attempt(
        sitting, "Ivan", {"q1": ["a"], "q2": ["a", "b"], "q3": "Common denominator"}
    )
    # olena: wrong, half of q2, no open answer = 1 of 6
    olena = make_attempt(sitting, "Olena", {"q1": ["b"], "q2": ["a"]}, order=["q3", "q2", "q1"])
    return ivan, olena


@pytest.fixture
def login(client, teacher):
    client.force_login(teacher)
    return client


# ---- permissions -------------------------------------------------------------------------


def test_login_required(client, sitting, attempts):
    for url in (
        reverse("reports:session", args=[sitting.pk]),
        reverse("reports:csv", args=[sitting.pk]),
        reverse("reports:attempt", args=[attempts[0].pk]),
    ):
        response = client.get(url)
        assert response.status_code == 302
        assert "login" in response["Location"]


def test_other_teacher_gets_404(client, other_teacher, sitting, attempts):
    client.force_login(other_teacher)
    assert client.get(reverse("reports:session", args=[sitting.pk])).status_code == 404
    assert client.get(reverse("reports:csv", args=[sitting.pk])).status_code == 404
    assert client.get(reverse("reports:attempt", args=[attempts[0].pk])).status_code == 404
    response = client.post(
        reverse("reports:attempt", args=[attempts[0].pk]),
        {"points_q3": "1"},
    )
    assert response.status_code == 404
    assert Answer.objects.get(attempt=attempts[0], question_key="q3").manual_score is None


def test_admin_sees_everything(client, sitting, attempts):
    admin = get_user_model().objects.create_user("boss", password="pw", role="admin")
    client.force_login(admin)
    assert client.get(reverse("reports:session", args=[sitting.pk])).status_code == 200
    assert client.get(reverse("reports:attempt", args=[attempts[0].pk])).status_code == 200


def test_unknown_ids_404(login):
    assert login.get(reverse("reports:session", args=[999])).status_code == 404
    assert login.get(reverse("reports:attempt", args=[999])).status_code == 404


# ---- session summary ---------------------------------------------------------------------


def test_session_summary(login, sitting, attempts):
    response = login.get(reverse("reports:session", args=[sitting.pk]))
    assert response.status_code == 200
    html = response.content.decode()
    summary = response.context["summary"]
    assert summary.takers == 2
    assert summary.average_percent == D("33.4")  # (50.0 + 16.7) / 2 = 33.35, half up
    assert summary.median_percent == D("33.4")
    assert summary.pending_answers == 1
    assert "Ivan" in html and "Olena" in html
    assert "<progress" in html
    assert 'style="' not in html
    assert reverse("reports:csv", args=[sitting.pk]) in html
    assert reverse("reports:attempt", args=[attempts[0].pk]) in html


def test_session_distribution_buckets(login, sitting, attempts):
    summary = login.get(reverse("reports:session", args=[sitting.pk])).context["summary"]
    counts = {b["label"]: b["count"] for b in summary.distribution}
    assert counts["10–19 %"] == 1
    assert counts["50–59 %"] == 1
    assert sum(counts.values()) == 2


def test_item_analysis(login, sitting, attempts):
    groups = login.get(reverse("reports:session", args=[sitting.pk])).context["item_groups"]
    assert [g["label"] for g in groups] == [""]  # a test without variants: one group
    items = groups[0]["items"]
    by_id = {i["id"]: i for i in items}
    assert by_id["q1"]["percent"] == D("50.0")  # one of two correct
    assert by_id["q1"]["top_wrong"] == {"text": "Lviv", "count": 1}
    assert by_id["q2"]["percent"] == D("75.0")  # 2 + 1 of 4
    assert by_id["q3"]["percent"] == D("0.0")  # pending, 0 so far


def test_attempts_sorting_and_filter(login, sitting, attempts):
    url = reverse("reports:session", args=[sitting.pk])
    names = lambda r: [row["name"] for row in r.context["rows"]]  # noqa: E731
    assert names(login.get(url, {"sort": "name"})) == ["Ivan", "Olena"]
    assert names(login.get(url, {"sort": "-name"})) == ["Olena", "Ivan"]
    assert names(login.get(url, {"sort": "-score"})) == ["Ivan", "Olena"]
    assert names(login.get(url, {"sort": "score"})) == ["Olena", "Ivan"]
    assert names(login.get(url, {"status": "needs_review"})) == ["Ivan"]
    assert names(login.get(url, {"sort": "bogus", "status": "bogus"})) == ["Ivan", "Olena"]
    make_attempt(sitting, "Petro", {"q1": ["a"]}, status=Attempt.Status.IN_PROGRESS)
    assert names(login.get(url, {"status": "in_progress"})) == ["Petro"]
    assert login.get(url).context["summary"].takers == 2  # in-progress attempts don't count


def test_session_with_no_attempts(login, sitting):
    response = login.get(reverse("reports:session", args=[sitting.pk]))
    assert response.status_code == 200
    assert response.context["summary"].takers == 0


def test_grading_disabled_session(login, sitting):
    doc = {**DOC, "test": {**DOC["test"], "grading": {"enabled": False}}}
    sitting.revision.document = doc
    sitting.revision.save()
    attempt = make_attempt(sitting, "Ivan", {"q1": ["a"]})
    assert login.get(reverse("reports:session", args=[sitting.pk])).status_code == 200
    html = login.get(reverse("reports:attempt", args=[attempt.pk])).content.decode()
    assert "Grading is disabled" in html
    assert "Save" not in html  # no review forms


# ---- attempt sheet -----------------------------------------------------------------------


def test_sheet_shows_text_not_ids_and_totals(login, attempts):
    ivan = attempts[0]
    html = login.get(reverse("reports:attempt", args=[ivan.pk])).content.decode()
    assert "Ivan" in html and "7-A" in html
    assert "3 / 6" in html and "50.0 %" in html
    assert "Provisional" in html
    assert "Kyiv" in html and "two" in html and "three" in html
    assert "Common denominator" in html
    assert "Mention denominators" in html  # rubric for open questions
    assert "Needs review" in html
    assert 'style="' not in html


def test_sheet_follows_question_order(login, attempts):
    olena = attempts[1]
    rows = login.get(reverse("reports:attempt", args=[olena.pk])).context["rows"]
    assert [r.question["id"] for r in rows] == ["q3", "q2", "q1"]
    ivan_rows = login.get(reverse("reports:attempt", args=[attempts[0].pk])).context["rows"]
    assert [r.question["id"] for r in ivan_rows] == ["q1", "q2", "q3"]  # fallback: document order


def test_sheet_markers(login, attempts):
    rows = login.get(reverse("reports:attempt", args=[attempts[1].pk])).context["rows"]
    markers = {r.question["id"]: r.marker for r in rows}
    assert markers == {"q1": "wrong", "q2": "partial", "q3": "unanswered"}
    rows = login.get(reverse("reports:attempt", args=[attempts[0].pk])).context["rows"]
    markers = {r.question["id"]: r.marker for r in rows}
    assert markers == {"q1": "correct", "q2": "correct", "q3": "pending"}


def test_review_form_only_for_answers_needing_review(login, attempts):
    html = login.get(reverse("reports:attempt", args=[attempts[0].pk])).content.decode()
    assert html.count('name="points_') == 1 and 'name="points_q3"' in html
    assert html.count('name="comment_') == 1
    html = login.get(reverse("reports:attempt", args=[attempts[1].pk])).content.decode()
    assert 'name="points_' not in html


def test_review_fields_belong_to_one_form(login, attempts):
    html = login.get(reverse("reports:attempt", args=[attempts[0].pk])).content.decode()
    assert html.count('id="review-form"') == 1
    assert html.count('form="review-form"') >= 4  # points, comment and two buttons
    assert 'name="action" value="save"' in html


def test_sheet_heading_is_the_student(login, attempts):
    response = login.get(reverse("reports:attempt", args=[attempts[0].pk]))
    html = response.content.decode()
    assert "<h1>Ivan</h1>" in html
    assert "<title>Ivan - Mixed quiz" in html


def test_review_saves_manual_score_and_regrades(login, attempts):
    ivan = attempts[0]
    url = reverse("reports:attempt", args=[ivan.pk])
    response = login.post(url, {"points_q3": "2,5", "comment_q3": "Add example"})
    assert response.status_code == 302
    assert response["Location"] == url

    answer = Answer.objects.get(attempt=ivan, question_key="q3")
    assert answer.manual_score == D("2.5")
    assert answer.feedback == "Add example"
    assert answer.status == "reviewed"
    ivan.refresh_from_db()
    assert ivan.pending_reviews == 0
    assert ivan.score == D("5.50")
    assert ivan.percent == D("91.7")

    html = login.get(url).content.decode()
    assert "Provisional" not in html
    assert "Add example" in html
    assert 'value="2.5"' in html  # reviewed answers stay editable
    # edit it again
    login.post(url, {"points_q3": "1", "comment_q3": ""})
    ivan.refresh_from_db()
    assert ivan.score == D("4.00")


@pytest.mark.parametrize("points", ["abc", "-1", "3.5", "0.3", "1e1", "NaN", "Infinity"])
def test_review_rejects_invalid_points(login, attempts, points):
    ivan = attempts[0]
    url = reverse("reports:attempt", args=[ivan.pk])
    response = login.post(url, {"points_q3": points, "comment_q3": "kept text"})
    assert response.status_code == 200  # re-rendered, nothing lost
    html = response.content.decode()
    assert "Question 3 was not saved" in html
    assert "kept text" in html and f'value="{points}"' in html
    assert Answer.objects.get(attempt=ivan, question_key="q3").manual_score is None
    ivan.refresh_from_db()
    assert ivan.pending_reviews == 1


def test_review_empty_points_leave_the_answer_alone(login, attempts):
    ivan = attempts[0]
    url = reverse("reports:attempt", args=[ivan.pk])
    response = login.post(url, {"points_q3": "", "comment_q3": ""})
    assert response.status_code == 302
    assert Answer.objects.get(attempt=ivan, question_key="q3").manual_score is None
    # a comment without points is reported, not silently dropped
    response = login.post(url, {"points_q3": "", "comment_q3": "Nice"})
    assert response.status_code == 200
    assert "Enter points to save the comment" in response.content.decode()


def test_review_ignores_non_reviewable_answers(login, attempts):
    ivan = attempts[0]
    url = reverse("reports:attempt", args=[ivan.pk])
    login.post(url, {"points_q1": "0", "points_nope": "0"})
    assert Answer.objects.get(attempt=ivan, question_key="q1").manual_score is None


def test_review_boundaries_accept_zero_and_max(login, attempts):
    ivan = attempts[0]
    url = reverse("reports:attempt", args=[ivan.pk])
    login.post(url, {"points_q3": "0"})
    assert Answer.objects.get(attempt=ivan, question_key="q3").manual_score == D("0")
    login.post(url, {"points_q3": "3"})
    assert Answer.objects.get(attempt=ivan, question_key="q3").manual_score == D("3")


def test_review_requires_csrf_token_in_form(login, attempts):
    html = login.get(reverse("reports:attempt", args=[attempts[0].pk])).content.decode()
    assert "csrfmiddlewaretoken" in html


@pytest.fixture
def two_open(sitting):
    doc = {
        **DOC,
        "test": {
            **DOC["test"],
            "questions": [
                *DOC["test"]["questions"],
                {"id": "q4", "type": "open", "text": "Why?", "points": 2},
            ],
        },
    }
    sitting.revision.document = doc
    sitting.revision.save()
    return make_attempt(sitting, "Zoya", {"q1": ["a"], "q3": "text", "q4": "because"})


def test_one_post_grades_two_open_answers(login, two_open):
    url = reverse("reports:attempt", args=[two_open.pk])
    assert two_open.pending_reviews == 2
    login.post(url, {"points_q3": "2", "comment_q3": "ok", "points_q4": "1.5"})
    two_open.refresh_from_db()
    assert two_open.pending_reviews == 0
    assert Answer.objects.get(attempt=two_open, question_key="q4").manual_score == D("1.5")
    assert two_open.score == D("4.50")  # 1 + 0 + 2 + 1.5


def test_bad_row_does_not_block_the_other(login, two_open):
    url = reverse("reports:attempt", args=[two_open.pk])
    response = login.post(url, {"points_q3": "9", "points_q4": "2"})
    assert response.status_code == 200
    assert "Question 3 was not saved" in response.content.decode()
    assert Answer.objects.get(attempt=two_open, question_key="q4").manual_score == D("2")
    assert Answer.objects.get(attempt=two_open, question_key="q3").manual_score is None
    two_open.refresh_from_db()
    assert two_open.pending_reviews == 1


def test_next_unreviewed_link(login, sitting, attempts):
    ivan, olena = attempts
    third = make_attempt(sitting, "Zoya", {"q3": "text"})
    html_ivan = login.get(reverse("reports:attempt", args=[ivan.pk])).content.decode()
    assert reverse("reports:attempt", args=[third.pk]) in html_ivan
    assert login.get(reverse("reports:attempt", args=[ivan.pk])).context["next_attempt"] == third
    # wraps around to the first pending attempt
    assert login.get(reverse("reports:attempt", args=[third.pk])).context["next_attempt"] == ivan
    # nothing else pending -> no link
    login.post(reverse("reports:attempt", args=[third.pk]), {"points_q3": "1"})
    assert login.get(reverse("reports:attempt", args=[ivan.pk])).context["next_attempt"] is None


def test_save_and_next_walks_through_pending_attempts(login, sitting, attempts):
    ivan, olena = attempts
    third = make_attempt(sitting, "Zoya", {"q3": "text"})
    first = reverse("reports:attempt", args=[ivan.pk])
    response = login.post(first, {"points_q3": "1", "action": "next"})
    assert response["Location"] == reverse("reports:attempt", args=[third.pk])
    response = login.post(
        reverse("reports:attempt", args=[third.pk]), {"points_q3": "2", "action": "next"}
    )
    assert response["Location"] == reverse("reports:session", args=[sitting.pk])
    response = login.get(response["Location"])
    assert "Everything in this session is reviewed" in response.content.decode()


def test_save_and_next_stays_when_a_row_is_invalid(login, sitting, attempts):
    make_attempt(sitting, "Zoya", {"q3": "text"})
    response = login.post(
        reverse("reports:attempt", args=[attempts[0].pk]), {"points_q3": "99", "action": "next"}
    )
    assert response.status_code == 200


def test_next_button_on_last_pending_attempt_returns_to_results(login, sitting, attempts):
    html = login.get(reverse("reports:attempt", args=[attempts[0].pk])).content.decode()
    assert "Save and return to the results" in html
    assert "Save and go to the next unreviewed attempt" not in html
    make_attempt(sitting, "Zoya", {"q3": "text"})
    html = login.get(reverse("reports:attempt", args=[attempts[0].pk])).content.decode()
    assert "Save and go to the next unreviewed attempt" in html


# ---- cancelling an attempt ---------------------------------------------------------------


def test_void_requires_login_and_ownership(client, other_teacher, attempts):
    url = reverse("reports:attempt_void", args=[attempts[0].pk])
    assert client.get(url).status_code == 302
    assert client.post(url).status_code == 302
    client.force_login(other_teacher)
    assert client.get(url).status_code == 404
    assert client.post(url).status_code == 404
    attempts[0].refresh_from_db()
    assert attempts[0].status == Attempt.Status.SUBMITTED
    assert client.get(reverse("reports:attempt_void", args=[999])).status_code == 404


def test_void_get_confirms_and_changes_nothing(login, attempts):
    url = reverse("reports:attempt_void", args=[attempts[0].pk])
    response = login.get(url)
    assert response.status_code == 200
    html = response.content.decode()
    assert "Ivan" in html and "3 / 6" in html and "cannot be undone" in html
    assert 'style="' not in html
    attempts[0].refresh_from_db()
    assert attempts[0].status == Attempt.Status.SUBMITTED


def test_void_post_cancels_and_returns_to_results(login, sitting, attempts):
    ivan, olena = attempts
    response = login.post(reverse("reports:attempt_void", args=[ivan.pk]))
    assert response["Location"] == reverse("reports:session", args=[sitting.pk])
    ivan.refresh_from_db()
    assert ivan.status == Attempt.Status.VOIDED
    assert ivan.score == D("3.00")  # the teacher can still see it

    page = login.get(response["Location"])
    assert [r["name"] for r in page.context["rows"]] == ["Olena"]
    assert page.context["summary"].takers == 1
    assert page.context["first_pending"] is None  # a voided attempt waits for nobody
    assert "cancelled" in page.content.decode()
    voided = login.get(response["Location"], {"status": "voided"})
    assert [r["name"] for r in voided.context["rows"]] == ["Ivan"]
    needs = login.get(response["Location"], {"status": "needs_review"})
    assert needs.context["rows"] == []


def test_void_is_idempotent_and_hides_actions(login, attempts):
    ivan = attempts[0]
    login.post(reverse("reports:attempt_void", args=[ivan.pk]))
    response = login.get(reverse("reports:attempt_void", args=[ivan.pk]))
    assert response.status_code == 302  # already cancelled: back to the sheet
    html = login.get(reverse("reports:attempt", args=[ivan.pk])).content.decode()
    assert "This attempt was cancelled" in html
    assert reverse("reports:attempt_void", args=[ivan.pk]) not in html
    assert 'name="points_' not in html  # no review of a cancelled attempt


def test_sheet_offers_cancel_button(login, attempts):
    html = login.get(reverse("reports:attempt", args=[attempts[0].pk])).content.decode()
    assert reverse("reports:attempt_void", args=[attempts[0].pk]) in html
    assert "Cancel attempt" in html


# ---- results page polish -----------------------------------------------------------------


def test_sort_links_show_state(login, sitting, attempts):
    url = reverse("reports:session", args=[sitting.pk])
    html = login.get(url, {"sort": "name"}).content.decode()
    assert 'aria-sort="ascending"' in html
    assert html.count("aria-sort=") == 1
    html = login.get(url, {"sort": "-score"}).content.decode()
    assert 'aria-sort="descending"' in html and "↓" in html


def test_provisional_is_flagged_once_with_a_footnote(login, sitting, attempts):
    html = login.get(reverse("reports:session", args=[sitting.pk])).content.decode()
    assert html.count("(needs review)") == 1
    assert "* Provisional" in html
    assert 'class="cell-title"' in html and "table-compact" in html


# ---- CSV ---------------------------------------------------------------------------------


def parse_csv(response):
    text = response.content.decode("utf-8-sig")
    return list(csv.reader(io.StringIO(text)))


def test_csv_export(login, sitting, attempts):
    response = login.get(reverse("reports:csv", args=[sitting.pk]))
    assert response.status_code == 200
    assert response["Content-Type"].startswith("text/csv")
    assert "ABC234" in response["Content-Disposition"]
    rows = parse_csv(response)
    header = rows[0]
    assert header[:2] == ["Full name", "Class"]
    assert header[-3:] == ["1. q1", "2. q2", "3. q3"]
    by_name = {r[0]: dict(zip(header, r, strict=True)) for r in rows[1:]}
    assert len(by_name) == 2
    ivan = by_name["Ivan"]
    assert ivan["Status"] == "submitted"
    assert ivan["Score"] == "3.00" and ivan["Max score"] == "6.00" and ivan["Percent"] == "50.0"
    assert ivan["Grade"] == "50.0 %"
    assert ivan["Pending reviews"] == "1"
    assert (ivan["1. q1"], ivan["2. q2"], ivan["3. q3"]) == ("1.00", "2.00", "0.00")
    olena = by_name["Olena"]
    assert (olena["1. q1"], olena["2. q2"], olena["3. q3"]) == ("0.00", "1.00", "0.00")


def test_csv_neutralises_formulas(login, sitting):
    make_attempt(sitting, "=HYPERLINK(1)", {"q1": ["a"]})
    rows = parse_csv(login.get(reverse("reports:csv", args=[sitting.pk])))
    assert rows[1][0] == "'=HYPERLINK(1)"


def test_csv_empty_session(login, sitting):
    rows = parse_csv(login.get(reverse("reports:csv", args=[sitting.pk])))
    assert len(rows) == 1
