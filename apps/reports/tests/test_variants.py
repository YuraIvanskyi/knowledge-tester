"""Results of a test with variants: the session table, per-variant question statistics, the
attempt sheet, the CSV and the PDF all follow each taker's own variant."""

import csv
import io
from decimal import Decimal as D
from io import BytesIO

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse
from pypdf import PdfReader

from apps.assessments.models import Assessment, Project, Revision
from apps.delivery import services
from apps.delivery.models import Sitting
from apps.exchange import variants
from apps.exchange.importer import import_document

pytestmark = pytest.mark.django_db


def choice(text, right, wrong, points=1):
    return {
        "type": "single_choice",
        "text": text,
        "points": points,
        "options": [{"text": right, "correct": True}, {"text": wrong}],
    }


RAW = {
    "format": "knowledge-tester/test",
    "version": 1,
    "test": {
        "title": "Parallel quiz",
        "variants": [
            {
                "questions": [
                    choice("Alpha one", "A-right", "A-wrong"),
                    choice("Alpha two", "A2-right", "A2-wrong", points=2),
                    {"type": "open", "text": "Alpha essay", "points": 2},
                ]
            },
            {
                "title": "Group B",
                "questions": [
                    choice("Beta one", "B-right", "B-wrong"),
                    choice("Beta two", "B2-right", "B2-wrong", points=2),
                ],
            },
        ],
    },
}


@pytest.fixture
def teacher():
    return get_user_model().objects.create_user("teacher", password="pw")


@pytest.fixture
def login(client, teacher):
    client.force_login(teacher)
    return client


@pytest.fixture
def sitting(teacher):
    document = import_document(RAW).document
    project = Project.objects.create(owner=teacher, title="P")
    assessment = Assessment.objects.create(project=project, title="Quiz", document=document)
    revision = Revision.objects.create(
        assessment=assessment, number=1, document=document, content_hash="h"
    )
    return Sitting.objects.create(revision=revision, code="ABC234", created_by=teacher)


def take(sitting, variant_id, name, picks):
    """An attempt in the given variant. `picks`: per question in document order, True = the
    right option, False = the wrong one, None = no answer."""
    test = sitting.revision.test
    taken = {str(t) for t in sitting.attempts.values_list("token", flat=True)}
    for number in range(500):
        token = f"00000000-0000-4000-8000-{number:012d}"
        if token not in taken and variants.for_token(test, token) == variant_id:
            break
    attempt = services.start_attempt(sitting, {"name": name}, token=token)
    assert attempt.variant == variant_id
    answers = {}
    for question, pick in zip(attempt.test["questions"], picks, strict=False):
        if pick is None or question["type"] != "single_choice":
            continue
        wanted = [o["id"] for o in question["options"] if bool(o.get("correct")) == pick]
        answers[question["id"]] = wanted[:1]
    services.save_answers(attempt, attempt.test, answers)
    services.finalize(attempt)
    attempt.refresh_from_db()
    return attempt


@pytest.fixture
def attempts(sitting):
    return {
        "ann": take(sitting, "v1", "Ann", [True, True]),
        "bob": take(sitting, "v1", "Bob", [False, True]),
        "cy": take(sitting, "v2", "Cy", [True, False]),
    }


def test_session_table_has_a_variant_column(login, sitting, attempts):
    response = login.get(reverse("reports:session", args=[sitting.pk]))
    html = response.content.decode()
    assert response.context["has_variants"] is True
    assert html.count('data-label="Variant">Variant 1<') == 2
    assert html.count('data-label="Variant">Group B<') == 1


def test_question_statistics_are_per_variant_over_its_own_takers(login, sitting, attempts):
    groups = login.get(reverse("reports:session", args=[sitting.pk])).context["item_groups"]
    assert [(g["label"], g["takers"]) for g in groups] == [("Variant 1", 2), ("Group B", 1)]
    first = {i["text"]: i for i in groups[0]["items"]}
    assert first["Alpha one"]["percent"] == D("50.0")  # Ann right, Bob wrong: of 2, not of 3
    assert first["Alpha one"]["top_wrong"] == {"text": "A-wrong", "count": 1}
    assert first["Alpha two"]["percent"] == D("100.0")
    second = {i["text"]: i for i in groups[1]["items"]}
    assert second["Beta one"]["percent"] == D("100.0")  # the only taker of this variant
    assert second["Beta two"]["percent"] == D("0.0")
    assert [i["number"] for i in groups[1]["items"]] == [1, 2]  # numbering restarts
    html = login.get(reverse("reports:session", args=[sitting.pk])).content.decode()
    assert "Group B" in html and "2 finished attempts" in html and "1 finished attempt" in html


def test_attempt_sheet_shows_the_variant_and_only_its_questions(login, sitting, attempts):
    html = login.get(reverse("reports:attempt", args=[attempts["cy"].pk])).content.decode()
    assert "Group B" in html and "Beta one" in html and "Beta two" in html
    assert "Alpha one" not in html and "Alpha essay" not in html
    other = login.get(reverse("reports:attempt", args=[attempts["ann"].pk])).content.decode()
    assert "Variant 1" in other and "Alpha essay" in other and "Beta one" not in other


def test_review_of_an_open_answer_regrades_within_the_variant(login, sitting, attempts):
    ann = attempts["ann"]
    essay = ann.test["questions"][2]["id"]
    assert (ann.score, ann.max_score, ann.pending_reviews) == (D("3.00"), D("5.00"), 0)
    ann.answers.filter(question_key=essay).update(value="An essay")
    from apps.grading.service import grade_attempt

    grade_attempt(ann)
    ann.refresh_from_db()
    assert ann.pending_reviews == 1
    response = login.post(
        reverse("reports:attempt", args=[ann.pk]), {f"points_{essay}": "2", f"comment_{essay}": ""}
    )
    assert response.status_code == 302
    ann.refresh_from_db()
    assert (ann.score, ann.max_score, ann.pending_reviews) == (D("5.00"), D("5.00"), 0)


def test_csv_has_a_variant_column_and_columns_by_position(login, sitting, attempts):
    response = login.get(reverse("reports:csv", args=[sitting.pk]))
    rows = list(csv.reader(io.StringIO(response.content.decode("utf-8-sig"))))
    header = rows[0]
    assert header[1] == "Variant"
    assert header[-3:] == ["1.", "2.", "3."]  # the longest variant has three questions
    by_name = {r[0]: r for r in rows[1:]}
    assert by_name["Ann"][1] == "Variant 1" and by_name["Cy"][1] == "Group B"
    assert by_name["Ann"][-3:] == ["1.00", "2.00", "0.00"]
    assert by_name["Bob"][-3:] == ["0.00", "2.00", "0.00"]
    assert by_name["Cy"][-3:] == ["1.00", "0.00", ""]  # no third question in this variant


def test_pdf_sheet_names_the_variant_and_prints_its_questions(login, sitting, attempts):
    response = login.get(reverse("reports:attempt_pdf", args=[attempts["cy"].pk]))
    assert response.status_code == 200
    text = "\n".join(page.extract_text() for page in PdfReader(BytesIO(response.content)).pages)
    assert "Group B" in text and "Beta one" in text and "Alpha one" not in text
    batch = login.get(reverse("reports:session_pdf", args=[sitting.pk]))
    text = "\n".join(page.extract_text() for page in PdfReader(BytesIO(batch.content)).pages)
    assert (
        "Variant 1" in text and "Group B" in text and "Alpha essay" in text and "Beta two" in text
    )
