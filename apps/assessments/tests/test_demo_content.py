"""The Ukrainian demo tests in docs/examples/ua and the seed_demo command that loads them."""

import json
from decimal import Decimal
from pathlib import Path

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command

from apps.assessments.models import Assessment, Revision
from apps.exchange.importer import import_document
from apps.grading.engine import grade_answer, grade_test

UA_DIR = Path(__file__).resolve().parents[3] / "docs" / "examples" / "ua"
UA_FILES = sorted(UA_DIR.glob("*.json"))
ALL_TYPES = {"single_choice", "multiple_choice", "choose_n", "short_answer", "open"}

ids = lambda p: p.stem  # noqa: E731


def test_four_demo_files_exist():
    assert len(UA_FILES) == 4


@pytest.mark.parametrize("path", UA_FILES, ids=ids)
def test_file_is_valid_and_ukrainian(path):
    raw = path.read_text(encoding="utf-8")
    result = import_document(raw)
    assert result.ok, result.report.as_text()
    assert not result.report.warnings, result.report.as_text()
    test = result.document["test"]
    assert test["language"] == "uk"
    assert 5 <= len(test["questions"]) <= 12
    # already canonical enough: a re-import of the normalised document changes nothing
    assert import_document(result.document).document == result.document
    assert json.loads(raw)["test"]["title"] == test["title"]


def test_titles_are_unique():
    titles = [json.loads(p.read_text(encoding="utf-8"))["test"]["title"] for p in UA_FILES]
    assert len(set(titles)) == len(titles)


def test_every_question_type_is_covered():
    types = set()
    for path in UA_FILES:
        document = import_document(path.read_text(encoding="utf-8")).document
        types |= {q["type"] for q in document["test"]["questions"]}
    assert types == ALL_TYPES


def test_settings_and_scales_vary():
    documents = [import_document(p.read_text(encoding="utf-8")).document["test"] for p in UA_FILES]
    assert {"ua_12", "five_point", "pass_fail"} <= {d["grading"]["scale"] for d in documents}
    assert any(d["settings"]["time_limit_minutes"] for d in documents)
    assert any(d["settings"]["one_question_per_page"] for d in documents)
    assert any(d["settings"]["shuffle_questions"] for d in documents)
    assert len({d["settings"]["show_result"] for d in documents}) >= 2
    scorings = {
        q.get("scoring")
        for d in documents
        for q in d["questions"]
        if q["type"] == "multiple_choice"
    }
    assert scorings == {"partial", "all_or_nothing", "per_option"}


# ---- seed_demo ------------------------------------------------------------------------------


@pytest.mark.django_db
def test_seed_demo_publishes_all_ukrainian_tests_idempotently():
    call_command("seed_demo")
    call_command("seed_demo")
    teacher = get_user_model().objects.get(username="teacher")
    assessments = Assessment.objects.filter(project__owner=teacher)
    expected = {json.loads(p.read_text(encoding="utf-8"))["test"]["title"] for p in UA_FILES}
    uk = assessments.filter(language="uk")
    assert {a.title for a in uk} == expected
    assert all(a.status == Assessment.Status.PUBLISHED for a in assessments)
    assert all(a.revisions.count() == 1 for a in assessments)
    assert Revision.objects.filter(assessment__in=uk).count() == len(UA_FILES)
    assert assessments.count() == len(UA_FILES) + 1  # plus the English docs/examples/full.json


def _all_correct_answers(document):
    answers = {}
    for q in document["test"]["questions"]:
        if q["type"] in ("single_choice", "multiple_choice", "choose_n"):
            answers[q["id"]] = [o["id"] for o in q["options"] if o["correct"]]
            if q.get("scoring") == "per_option":
                answers[q["id"]] = [o["id"] for o in q["options"] if o.get("weight", 0) > 0]
        elif q["type"] == "short_answer":
            answers[q["id"]] = q["accept"][0]
        else:
            answers[q["id"]] = "Розгорнута відповідь учня."
    return answers


@pytest.mark.django_db
@pytest.mark.parametrize("path", UA_FILES, ids=ids)
def test_seeded_test_grades_full_marks_with_correct_answers(path):
    call_command("seed_demo")
    title = json.loads(path.read_text(encoding="utf-8"))["test"]["title"]
    revision = Revision.objects.get(assessment__title=title)
    document = revision.document
    result = grade_test(document["test"], _all_correct_answers(document))

    has_open = any(q["type"] == "open" for q in document["test"]["questions"])
    assert result.pending_reviews == (1 if has_open else 0)
    assert result.provisional == has_open
    # every automatically graded question earns its full points; open ones await the teacher
    for question in document["test"]["questions"]:
        r = result.per_question[question["id"]]
        if question["type"] == "open":
            assert r.status == "needs_review"
        else:
            assert (r.status, r.points) == ("graded", r.max_points), question["text"]
    assert result.max_score > Decimal(0)


@pytest.mark.parametrize("variant", ["м'яч", "мʼяч", "м’яч", "М'ЯЧ", "  м’яч. "])
def test_apostrophe_variants_are_accepted(variant):
    document = import_document(
        (UA_DIR / "ukrainska-mova-orfohrafiia.json").read_text(encoding="utf-8")
    ).document
    question = next(q for q in document["test"]["questions"] if "м'яч" in q.get("accept", []))
    assert grade_answer(question, variant).points == Decimal("1.00")
