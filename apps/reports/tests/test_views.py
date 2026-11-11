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
        {"question_key": "q3", "points": "1"},
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
    items = login.get(reverse("reports:session", args=[sitting.pk])).context["items"]
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
    assert html.count('name="question_key"') == 1
    html = login.get(reverse("reports:attempt", args=[attempts[1].pk])).content.decode()
    assert 'name="question_key"' not in html


def test_review_saves_manual_score_and_regrades(login, attempts):
    ivan = attempts[0]
    url = reverse("reports:attempt", args=[ivan.pk])
    response = login.post(url, {"question_key": "q3", "points": "2,5", "comment": "Add example"})
    assert response.status_code == 302
    assert response["Location"].startswith(url)

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
    login.post(url, {"question_key": "q3", "points": "1", "comment": ""})
    ivan.refresh_from_db()
    assert ivan.score == D("4.00")


@pytest.mark.parametrize("points", ["", "abc", "-1", "3.5", "0.3", "1e1", "NaN", "Infinity"])
def test_review_rejects_invalid_points(login, attempts, points):
    ivan = attempts[0]
    login.post(reverse("reports:attempt", args=[ivan.pk]), {"question_key": "q3", "points": points})
    assert Answer.objects.get(attempt=ivan, question_key="q3").manual_score is None
    ivan.refresh_from_db()
    assert ivan.pending_reviews == 1


def test_review_rejects_non_reviewable_answer(login, attempts):
    ivan = attempts[0]
    login.post(reverse("reports:attempt", args=[ivan.pk]), {"question_key": "q1", "points": "0"})
    assert Answer.objects.get(attempt=ivan, question_key="q1").manual_score is None
    login.post(reverse("reports:attempt", args=[ivan.pk]), {"question_key": "nope", "points": "0"})


def test_review_boundaries_accept_zero_and_max(login, attempts):
    ivan = attempts[0]
    url = reverse("reports:attempt", args=[ivan.pk])
    login.post(url, {"question_key": "q3", "points": "0"})
    assert Answer.objects.get(attempt=ivan, question_key="q3").manual_score == D("0")
    login.post(url, {"question_key": "q3", "points": "3"})
    assert Answer.objects.get(attempt=ivan, question_key="q3").manual_score == D("3")


def test_review_requires_csrf_token_in_form(login, attempts):
    html = login.get(reverse("reports:attempt", args=[attempts[0].pk])).content.decode()
    assert "csrfmiddlewaretoken" in html


def test_next_unreviewed_link(login, sitting, attempts):
    ivan, olena = attempts
    third = make_attempt(sitting, "Zoya", {"q3": "text"})
    html_ivan = login.get(reverse("reports:attempt", args=[ivan.pk])).content.decode()
    assert reverse("reports:attempt", args=[third.pk]) in html_ivan
    assert login.get(reverse("reports:attempt", args=[ivan.pk])).context["next_attempt"] == third
    # wraps around to the first pending attempt
    assert login.get(reverse("reports:attempt", args=[third.pk])).context["next_attempt"] == ivan
    # nothing else pending -> no link
    login.post(reverse("reports:attempt", args=[third.pk]), {"question_key": "q3", "points": "1"})
    assert login.get(reverse("reports:attempt", args=[ivan.pk])).context["next_attempt"] is None


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
