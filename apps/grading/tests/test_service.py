from decimal import Decimal as D

import pytest
from django.contrib.auth import get_user_model

from apps.assessments.models import Assessment, Project, Revision
from apps.delivery.models import Answer, Attempt, Sitting
from apps.grading.service import grade_attempt

pytestmark = pytest.mark.django_db

DOC = {
    "format": "knowledge-tester/test",
    "version": 1,
    "test": {
        "title": "Mixed",
        "grading": {"enabled": True, "scale": "points"},
        "questions": [
            {
                "id": "q1",
                "type": "single_choice",
                "text": "One",
                "points": 1,
                "options": [{"id": "a", "text": "A", "correct": True}, {"id": "b", "text": "B"}],
            },
            {
                "id": "q2",
                "type": "short_answer",
                "text": "Two",
                "points": 1,
                "accept": ["Kyiv"],
                "review_unmatched": True,
            },
            {"id": "q3", "type": "open", "text": "Three", "points": 3},
            {
                "id": "q4",
                "type": "choose_n",
                "text": "Four",
                "points": 2,
                "n": 2,
                "options": [
                    {"id": "a", "text": "A", "correct": True},
                    {"id": "b", "text": "B", "correct": True},
                    {"id": "c", "text": "C"},
                ],
            },
        ],
    },
}


@pytest.fixture
def make_attempt():
    def _make(document=DOC, answers=None):
        user = get_user_model().objects.create_user("teacher", password="x")
        project = Project.objects.create(owner=user, title="P")
        assessment = Assessment.objects.create(project=project, title="T", document=document)
        revision = Revision.objects.create(
            assessment=assessment, number=1, document=document, content_hash="x"
        )
        sitting = Sitting.objects.create(revision=revision, code="ABC234", created_by=user)
        attempt = Attempt.objects.create(
            sitting=sitting, taker={"name": "Ivan"}, status=Attempt.Status.SUBMITTED
        )
        for key, value in (answers or {}).items():
            Answer.objects.create(attempt=attempt, question_key=key, value=value)
        return attempt

    return _make


def by_key(attempt):
    return {a.question_key: a for a in attempt.answers.all()}


def test_grade_attempt_writes_answers_and_totals(make_attempt):
    attempt = make_attempt(answers={"q1": ["a"], "q2": "Kyev", "q3": "essay", "q4": ["a", "c"]})
    grade_attempt(attempt)

    attempt.refresh_from_db()
    answers = by_key(attempt)
    assert answers["q1"].auto_score == D("1.00") and answers["q1"].status == "graded"
    assert answers["q2"].auto_score == D("0.00") and answers["q2"].status == "needs_review"
    assert answers["q3"].status == "needs_review"
    assert answers["q4"].auto_score == D("1.00") and answers["q4"].status == "graded"
    assert (attempt.score, attempt.max_score, attempt.percent) == (D("2.00"), D("7.00"), D("28.6"))
    assert attempt.grade == "2 / 7"
    assert attempt.pending_reviews == 2


def test_missing_answers_are_created_as_unanswered(make_attempt):
    attempt = make_attempt(answers={"q1": ["b"]})
    grade_attempt(attempt)

    answers = by_key(attempt)
    assert set(answers) == {"q1", "q2", "q3", "q4"}
    assert answers["q2"].status == "unanswered"
    assert answers["q2"].auto_score == D("0.00")
    assert answers["q3"].status == "unanswered"
    attempt.refresh_from_db()
    assert attempt.score == D("0.00")
    assert attempt.max_score == D("7.00")
    assert attempt.pending_reviews == 0


def test_grade_attempt_is_idempotent(make_attempt):
    attempt = make_attempt(answers={"q1": ["a"], "q3": "essay"})
    grade_attempt(attempt)
    first = (
        {k: (a.auto_score, a.status) for k, a in by_key(attempt).items()},
        (attempt.score, attempt.max_score, attempt.percent, attempt.grade),
    )
    grade_attempt(attempt)
    grade_attempt(attempt)
    second = (
        {k: (a.auto_score, a.status) for k, a in by_key(attempt).items()},
        (attempt.score, attempt.max_score, attempt.percent, attempt.grade),
    )
    assert first == second
    assert attempt.answers.count() == 4


def test_manual_score_wins_and_marks_reviewed(make_attempt):
    attempt = make_attempt(answers={"q1": ["a"], "q2": "Kyev", "q3": "essay"})
    grade_attempt(attempt)
    attempt.refresh_from_db()
    assert attempt.pending_reviews == 2

    Answer.objects.filter(attempt=attempt, question_key="q3").update(
        manual_score=D("2.5"), feedback="Good"
    )
    grade_attempt(attempt)
    attempt.refresh_from_db()
    answers = by_key(attempt)
    assert answers["q3"].status == "reviewed"
    assert answers["q3"].auto_score == D("0.00")  # auto score stays automatic
    assert answers["q3"].points == D("2.50")
    assert attempt.pending_reviews == 1
    assert attempt.score == D("3.50")

    Answer.objects.filter(attempt=attempt, question_key="q2").update(manual_score=D("1"))
    grade_attempt(attempt)
    attempt.refresh_from_db()
    assert by_key(attempt)["q2"].status == "reviewed"
    assert attempt.pending_reviews == 0
    assert attempt.score == D("4.50")


def test_regrade_after_answer_change_keeps_manual_score(make_attempt):
    attempt = make_attempt(answers={"q3": "essay"})
    Answer.objects.filter(attempt=attempt, question_key="q3").update(manual_score=D("1"))
    grade_attempt(attempt)
    attempt.refresh_from_db()
    assert attempt.score == D("1.00")
    assert by_key(attempt)["q3"].status == "reviewed"


def test_grading_disabled_scores_nothing(make_attempt):
    document = {
        **DOC,
        "test": {**DOC["test"], "grading": {"enabled": False}},
    }
    attempt = make_attempt(document, answers={"q1": ["a"], "q3": "essay"})
    grade_attempt(attempt)
    attempt.refresh_from_db()
    assert attempt.score is None and attempt.max_score is None and attempt.percent is None
    assert attempt.grade == ""
    assert attempt.pending_reviews == 0
    answers = by_key(attempt)
    assert answers["q1"].auto_score is None
    assert answers["q1"].status == "graded"
    assert answers["q3"].status == "graded"
    assert answers["q2"].status == "unanswered"


def test_uses_few_queries(make_attempt, django_assert_max_num_queries):
    attempt = make_attempt(answers={"q1": ["a"], "q2": "Kyiv", "q3": "essay", "q4": ["a", "b"]})
    with django_assert_max_num_queries(12):
        grade_attempt(attempt)
