"""The test as a printable PDF for a written (paper) test (F-07): content, options, view."""

import copy
import io

import pytest
from django.contrib.auth import get_user_model
from django.http import QueryDict
from django.urls import reverse
from django.utils import translation
from pypdf import PdfReader

from apps.assessments import editing
from apps.assessments.models import Assessment, Project
from apps.exchange.importer import import_document
from apps.reports import paper_pdf as paper

pytestmark = pytest.mark.django_db

DOC = {
    "format": "knowledge-tester/test",
    "version": 1,
    "test": {
        "title": "Fractions",
        "language": "en",
        "settings": {"shuffle_questions": True, "shuffle_options": True},
        "taker_fields": [
            {"key": "name", "label": "Full name", "required": True},
            {"key": "class", "label": "Class", "required": False},
        ],
        "questions": [
            {
                "id": "q1",
                "type": "single_choice",
                "text": "Which fraction equals 0.5?",
                "hint": "Think of halves.",
                "points": 1,
                "options": [
                    {"id": "a", "text": "one half", "correct": True},
                    {"id": "b", "text": "one third"},
                    {"id": "c", "text": "two thirds"},
                ],
            },
            {
                "id": "q2",
                "type": "multiple_choice",
                "text": "Select every fraction greater than 1/2.",
                "points": 2,
                "options": [
                    {"id": "a", "text": "three quarters", "correct": True},
                    {"id": "b", "text": "two fifths"},
                    {"id": "c", "text": "two thirds", "correct": True},
                ],
            },
            {
                "id": "q3",
                "type": "choose_n",
                "text": "Choose the 2 fractions equal to 1/2.",
                "points": 1.5,
                "n": 2,
                "options": [
                    {"id": "a", "text": "two fourths", "correct": True},
                    {"id": "b", "text": "three sixths", "correct": True},
                    {"id": "c", "text": "three fourths"},
                ],
            },
            {
                "id": "q4",
                "type": "short_answer",
                "text": "Write 3/4 as a decimal.",
                "points": 1,
                "accept": ["ZEBRA-ACCEPT"],
            },
            {
                "id": "q5",
                "type": "open",
                "text": "Explain how to compare fractions.",
                "points": 3,
                "rubric": "SECRET-RUBRIC",
            },
        ],
    },
}

UK_DOC = {
    "format": "knowledge-tester/test",
    "version": 1,
    "test": {
        "title": "Дроби: основи",
        "language": "uk",
        "taker_fields": [{"key": "name", "label": "Прізвище та ім'я", "required": True}],
        "questions": [
            {
                "id": "q1",
                "type": "single_choice",
                "text": "Яка столиця України?",
                "points": 1,
                "options": [
                    {"id": "a", "text": "Львів"},
                    {"id": "b", "text": "Київ", "correct": True},
                ],
            },
            {
                "id": "q2",
                "type": "short_answer",
                "text": "Скільки буде 3/4 десятковим дробом?",
                "points": 1,
                "accept": ["0,75"],
            },
        ],
    },
}


def with_variants() -> dict:
    doc = copy.deepcopy(DOC)
    first = doc["test"].pop("questions")
    second = copy.deepcopy(first)
    for q in second:
        q["id"] = f"v2{q['id']}"
        q["text"] = "SECOND " + q["text"]
    doc["test"]["variants"] = [
        {"id": "v1", "title": "", "questions": first},
        {"id": "v2", "title": "Blue", "questions": second},
    ]
    return doc


def normalised(document: dict) -> dict:
    result = import_document(document)
    assert result.ok, result.report
    return result.document["test"]


def render(document: dict, **options) -> bytes:
    return paper.render_paper(normalised(document), paper.PaperOptions(**options))


def text_of(content: bytes) -> str:
    reader = PdfReader(io.BytesIO(content))
    return "\n".join(page.extract_text() for page in reader.pages)


def pages_of(content: bytes) -> list[str]:
    return [page.extract_text() for page in PdfReader(io.BytesIO(content)).pages]


# --- the answer sheet -----------------------------------------------------------------------


def test_sheet_has_questions_options_letters_and_blanks():
    content = render(DOC)
    assert content.startswith(b"%PDF")
    text = text_of(content)
    for expected in (
        "Fractions",
        "Full name:",
        "Class:",
        "Date:",
        "1. Which fraction equals 0.5?",
        "Think of halves.",
        "Choose one answer.",
        "A)  one half",
        "B)  one third",
        "C)  two thirds",
        "Select all that apply.",
        "Choose exactly 2.",
        "4. Write 3/4 as a decimal.",
        "Answer:",
        "5. Explain how to compare fractions.",
        "(1 point)",
        "(2 points)",
        "(1.5 points)",
        "(3 points)",
        "page 1/1",
    ):
        assert expected in text, expected


def test_sheet_keeps_the_tests_own_order_without_shuffling():
    text = text_of(render(DOC))
    positions = [text.index(f"{n}. ") for n in range(1, 6)]
    assert positions == sorted(positions)
    assert text.index("one half") < text.index("one third") < text.index("two thirds")


def test_no_answers_without_the_key():
    text = text_of(render(DOC))
    assert "ZEBRA-ACCEPT" not in text
    assert "SECRET-RUBRIC" not in text
    assert "Answer key" not in text
    assert "Accepted answers" not in text


def test_answer_key_on_its_own_pages_at_the_end():
    pages = pages_of(render(DOC, key=True))
    assert len(pages) >= 2
    key = pages[-1]
    assert "Answer key" in key and "For the teacher" in key
    assert "A  (one half)" in key
    assert "A, C  (three quarters; two thirds)" in key
    assert "A, B  (two fourths; three sixths)" in key
    assert "Accepted answers: ZEBRA-ACCEPT" in key
    assert "SECRET-RUBRIC" in key and "the teacher grades it" in key
    assert "Answer key" not in pages[0] and "ZEBRA-ACCEPT" not in pages[0]


def test_open_answers_get_more_lines_for_more_points():
    assert paper.open_lines(1) == 6
    assert paper.open_lines(2.5) == 6
    assert paper.open_lines(3) == 8
    assert paper.open_lines(4) == 10
    assert paper.open_lines(50) == 12


def test_points_labels():
    with translation.override("en"):
        assert paper.points_label(1) == "(1 point)"
        assert paper.points_label(2) == "(2 points)"
        assert paper.points_label(2.0) == "(2 points)"
        assert paper.points_label(0.5) == "(0.5 points)"


# --- language -------------------------------------------------------------------------------


def test_ukrainian_test_has_ukrainian_letters_and_labels_whatever_the_ui_language():
    with translation.override("en"):
        text = text_of(render(UK_DOC, key=True))
    for expected in (
        "Дроби: основи",
        "Прізвище та ім'я:",
        "Яка столиця України?",
        "А)  Львів",
        "Б)  Київ",
        "Відповідь:",  # existing catalog entry: the labels follow the test, not the UI
        "Дата:",
        "Б  (Київ)",
        "0,75",
    ):
        assert expected in text, expected
    assert "A)" not in text


def test_english_test_stays_english_in_the_ukrainian_ui():
    with translation.override("uk"):
        text = text_of(render(DOC))
    assert "Answer:" in text and "Date:" in text and "A)  one half" in text


def test_default_name_label_is_translated_for_a_ukrainian_test():
    doc = copy.deepcopy(UK_DOC)
    doc["test"]["taker_fields"] = [{"key": "name", "label": "Full name", "required": True}]
    assert "Прізвище та ім’я:" in text_of(render(doc))


def test_other_languages_use_the_ui_language():
    doc = copy.deepcopy(DOC)
    doc["test"]["language"] = "de"
    with translation.override("uk"):
        text = text_of(render(doc))
    assert "Відповідь:" in text and "A)  one half" in text


# --- variants and copies --------------------------------------------------------------------


def test_every_variant_by_default():
    pages = pages_of(render(with_variants()))
    assert len(pages) == 2
    assert "Variant 1" in pages[0] and "Which fraction" in pages[0] and "SECOND" not in pages[0]
    assert "Blue" in pages[1] and "SECOND Which fraction" in pages[1]
    assert "Fractions · Variant 1 · page 1/1" in pages[0]


def test_one_chosen_variant():
    text = text_of(render(with_variants(), variant="v2"))
    assert "Blue" in text and "SECOND" in text and "Variant 1" not in text


def test_key_per_variant():
    pages = pages_of(render(with_variants(), key=True))
    assert len(pages) == 4
    assert "Answer key · Variant 1" in pages[2] and "Answer key · Blue" in pages[3]


def test_copies_start_on_new_pages_and_number_their_own_pages():
    single = pages_of(render(DOC))
    copies = pages_of(render(DOC, copies=3))
    assert len(copies) == 3 * len(single)
    first_pages = copies[:: len(single)]
    assert all("Full name:" in page for page in first_pages)
    assert all(f"page 1/{len(single)}" in page for page in first_pages)


def test_long_test_numbers_pages_per_copy():
    doc = copy.deepcopy(DOC)
    questions = doc["test"]["questions"]
    for n in range(12):
        extra = copy.deepcopy(questions[4])
        extra["id"] = f"open{n}"
        questions.append(extra)
    pages = pages_of(render(doc, copies=2))
    per_copy = len(pages) // 2
    assert per_copy >= 2
    assert f"page 1/{per_copy}" in pages[per_copy]
    assert f"page {per_copy}/{per_copy}" in pages[-1]


def test_options_from_query():
    ids = ["v1", "v2"]
    parse = paper.PaperOptions.from_query
    assert parse(QueryDict(""), ids) == paper.PaperOptions()
    options = parse(QueryDict("opts=1&variant=v2&copies=25&key=1&paper=Letter"), ids)
    assert options == paper.PaperOptions(variant="v2", copies=25, key=True, paper="Letter")
    assert parse(QueryDict("variant=nope&copies=999"), ids).variant == "all"
    assert parse(QueryDict("copies=999"), ids).copies == paper.MAX_COPIES
    for junk in ("0", "-3", "abc", "١٢", "1e3", ""):
        assert parse(QueryDict(f"copies={junk}"), ids).copies in (1,), junk
    assert parse(QueryDict("opts=1"), ids).key is False
    assert parse(QueryDict("paper=A3"), ids).paper == "A4"


def test_letter_paper():
    reader = PdfReader(io.BytesIO(render(DOC, paper="Letter")))
    assert round(float(reader.pages[0].mediabox.width)) == 612


# --- robustness -----------------------------------------------------------------------------


def test_hostile_text_does_not_break_rendering():
    nasty = "x" * 400 + "\x00\x07​ <b>&</b> \U0001f600 " + "\n" * 5 + "ы" * 300
    doc = copy.deepcopy(DOC)
    doc["test"]["title"] = nasty[:200]
    for q in doc["test"]["questions"]:
        q["text"] = nasty
        for option in q.get("options", []):
            option["text"] = nasty[:300] + option["id"]
    doc["test"]["questions"][4]["rubric"] = nasty
    content = render(doc, key=True)
    assert content.startswith(b"%PDF")
    assert "\x00" not in text_of(content)


def test_many_options_run_out_of_letters_gracefully():
    doc = copy.deepcopy(DOC)
    doc["test"]["questions"][1]["options"] = [
        {"id": f"o{n}", "text": f"option {n}", "correct": n == 0} for n in range(20)
    ]
    text = text_of(render(doc))
    assert "T)  option 19" in text


def test_size_stays_small():
    assert len(render(DOC, copies=40, key=True)) < 400_000


# --- the view -------------------------------------------------------------------------------


@pytest.fixture
def teacher():
    return get_user_model().objects.create_user("teacher", password="pw")


def make_assessment(owner, document) -> Assessment:
    project = Project.objects.create(owner=owner, title="P")
    return Assessment.objects.create(
        project=project, title=document["test"]["title"], document=document
    )


def test_download(client, teacher):
    assessment = make_assessment(teacher, with_variants())
    client.force_login(teacher)
    url = reverse("assessments:paper_pdf", args=[assessment.pk])
    response = client.get(url, {"opts": "1", "variant": "v2", "copies": "2", "key": "1"})
    assert response.status_code == 200
    assert response["Content-Type"] == "application/pdf"
    assert response["Content-Disposition"].startswith("inline")
    assert "fractions_blue_written-test.pdf" in response["Content-Disposition"]
    pages = pages_of(response.content)
    assert len(pages) == 3  # two copies of Blue, then its key
    assert "SECOND" in pages[0] and "Answer key · Blue" in pages[2]


def test_unpublished_draft_prints_as_it_is_now(client, teacher):
    assessment = make_assessment(teacher, copy.deepcopy(DOC))
    assert not assessment.revisions.exists()
    client.force_login(teacher)
    response = client.get(reverse("assessments:paper_pdf", args=[assessment.pk]))
    assert response.status_code == 200
    assert "Which fraction equals 0.5?" in text_of(response.content)
    assert "ZEBRA-ACCEPT" not in text_of(response.content)  # no key by default


def test_invalid_test_goes_back_to_the_test_page(client, teacher):
    assessment = make_assessment(teacher, editing.blank_document("Empty", "en"))
    client.force_login(teacher)
    response = client.get(reverse("assessments:paper_pdf", args=[assessment.pk]), follow=True)
    assert response.redirect_chain[-1][0] == reverse("assessments:detail", args=[assessment.pk])
    assert "Cannot print" in response.content.decode()


def test_permissions(client, teacher, django_user_model):
    assessment = make_assessment(teacher, copy.deepcopy(DOC))
    url = reverse("assessments:paper_pdf", args=[assessment.pk])
    assert client.get(url).status_code == 302  # anonymous -> login
    client.force_login(django_user_model.objects.create_user("other", password="pw"))
    assert client.get(url).status_code == 404


def test_test_page_offers_the_print_form(client, teacher):
    client.force_login(teacher)
    plain = make_assessment(teacher, copy.deepcopy(DOC))
    html = client.get(reverse("assessments:detail", args=[plain.pk])).content.decode()
    assert reverse("assessments:paper_pdf", args=[plain.pk]) in html
    assert 'name="copies"' in html and 'name="key"' in html and 'name="variant"' not in html

    varied = make_assessment(teacher, with_variants())
    html = client.get(reverse("assessments:detail", args=[varied.pk])).content.decode()
    assert 'name="variant"' in html and 'value="v2"' in html and "Blue" in html

    empty = make_assessment(teacher, editing.blank_document("Empty", "en"))
    html = client.get(reverse("assessments:detail", args=[empty.pk])).content.decode()
    assert reverse("assessments:paper_pdf", args=[empty.pk]) not in html
