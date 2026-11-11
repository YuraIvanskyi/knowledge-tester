"""PDF sheets: content (Ukrainian included), options, batch, permissions, size."""

import io

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import translation
from fontTools.ttLib import TTFont
from pypdf import PdfReader

from apps.assessments.models import Assessment, Project, Revision
from apps.delivery.models import Answer, Attempt, Sitting
from apps.grading.service import grade_attempt
from apps.reports import pdf

pytestmark = pytest.mark.django_db

DOC = {
    "format": "knowledge-tester/test",
    "version": 1,
    "test": {
        "title": "Дроби: основи",
        "taker_fields": [
            {"key": "name", "label": "Прізвище та ім'я", "required": True},
            {"key": "class", "label": "Клас", "required": False},
        ],
        "grading": {"enabled": True, "scale": "ua_12"},
        "questions": [
            {
                "id": "q1",
                "type": "single_choice",
                "text": "Яка столиця України?",
                "points": 1,
                "options": [
                    {"id": "a", "text": "Київ", "correct": True},
                    {"id": "b", "text": "Львів"},
                ],
            },
            {
                "id": "q2",
                "type": "multiple_choice",
                "text": "Оберіть прості числа",
                "points": 2,
                "options": [
                    {"id": "a", "text": "два", "correct": True},
                    {"id": "b", "text": "три", "correct": True},
                    {"id": "c", "text": "чотири"},
                ],
            },
            {
                "id": "q3",
                "type": "short_answer",
                "text": "Скільки буде 3/4 десятковим дробом?",
                "points": 1,
                "accept": ["0.75"],
            },
            {
                "id": "q4",
                "type": "open",
                "text": "Поясніть, як порівняти дроби",
                "points": 3,
                "rubric": "Спільний знаменник",
            },
        ],
    },
}


@pytest.fixture
def teacher():
    return get_user_model().objects.create_user("teacher", password="pw")


@pytest.fixture
def sitting(teacher):
    project = Project.objects.create(owner=teacher, title="P")
    assessment = Assessment.objects.create(project=project, title="Дроби", document=DOC)
    revision = Revision.objects.create(
        assessment=assessment, number=1, document=DOC, content_hash="h"
    )
    return Sitting.objects.create(revision=revision, code="ABC234", created_by=teacher)


def make_attempt(sitting, name, answers, status=Attempt.Status.SUBMITTED, feedback=None):
    attempt = Attempt.objects.create(
        sitting=sitting,
        taker={"name": name, "class": "7-А"},
        status=status,
        question_order=["q1", "q2", "q3", "q4"],
        option_orders={"q1": ["a", "b"], "q2": ["a", "b", "c"]},
    )
    for key, value in answers.items():
        Answer.objects.create(
            attempt=attempt,
            question_key=key,
            value=value,
            feedback=(feedback or {}).get(key, ""),
        )
    if status != Attempt.Status.IN_PROGRESS:
        grade_attempt(attempt)
        attempt.refresh_from_db()
    return attempt


@pytest.fixture
def ivan(sitting):
    return make_attempt(
        sitting,
        "Іван Петренко",
        {"q1": ["b"], "q2": ["a"], "q3": "0,75", "q4": "Спільний знаменник"},
        feedback={"q4": "Додайте приклад."},
    )


@pytest.fixture
def login(client, teacher):
    client.force_login(teacher)
    return client


def text_of(content: bytes) -> str:
    reader = PdfReader(io.BytesIO(content))
    return "\n".join(page.extract_text() for page in reader.pages)


def render(attempts, **options):
    with translation.override("uk"):
        return pdf.render_pdf(attempts, pdf.PdfOptions(**options))


# --- the font -------------------------------------------------------------------------------


def test_bundled_font_covers_ukrainian_and_marks():
    wanted = "АБВГҐДЕЄЖЗИІЇЙКЛМНОПРСТУФХЦЧШЩЬЮЯабвгґдеєжзиіїйклмнопрстуфхцчшщьюя'’№✓…·"
    for name in ("DejaVuSans.ttf", "DejaVuSans-Bold.ttf"):
        cmap = TTFont(pdf.FONT_DIR / name).getBestCmap()
        missing = [c for c in wanted if ord(c) not in cmap]
        assert not missing, (name, missing)


# --- content --------------------------------------------------------------------------------


def test_compact_sheet_has_ukrainian_text(ivan):
    content = render([ivan])
    assert content.startswith(b"%PDF")
    text = text_of(content)
    for expected in (
        "Дроби: основи",
        "Іван Петренко",
        "7-А",
        "Яка столиця України?",
        "Відповідь: Львів",
        "Поясніть, як порівняти дроби",
        "Спільний знаменник",
        "Додайте приклад.",
    ):
        assert expected in text, expected
    assert "ABC234" in text
    assert "1/1" in text  # page numbers


def test_correct_answers_can_be_hidden(ivan):
    shown = text_of(render([ivan], show_correct=True))
    hidden = text_of(render([ivan], show_correct=False))
    assert "Київ" in shown and "Київ" not in hidden


def test_comments_can_be_hidden(ivan):
    assert "Додайте приклад." not in text_of(render([ivan], show_comments=False))


def test_full_mode_lists_every_option_with_marks(ivan):
    text = text_of(render([ivan], mode="full"))
    assert "[x] Львів" in text and "[ ] Київ" in text
    assert "Київ" in text and "✓" in text
    assert "три" in text and "чотири" in text


def test_unanswered_questions_can_be_dropped(sitting):
    attempt = make_attempt(sitting, "Олена", {"q1": ["a"]})
    assert "Яка столиця" in text_of(render([attempt], show_unanswered=False))
    text = text_of(render([attempt], show_unanswered=False))
    assert "Оберіть прості числа" not in text
    assert "Оберіть прості числа" in text_of(render([attempt], show_unanswered=True))


def test_provisional_total_is_labelled(ivan):
    assert ivan.pending_reviews == 1
    assert "Попередній" in text_of(render([ivan])) or "Provisional" in text_of(render([ivan]))


def test_shorten_cuts_long_question_text(sitting):
    long_doc = {**DOC, "test": {**DOC["test"], "questions": [dict(DOC["test"]["questions"][3])]}}
    long_doc["test"]["questions"][0]["text"] = "слово " * 100
    revision = Revision.objects.create(
        assessment=sitting.revision.assessment, number=2, document=long_doc, content_hash="h2"
    )
    other = Sitting.objects.create(revision=revision, code="LONG22", created_by=sitting.created_by)
    attempt = Attempt.objects.create(sitting=other, taker={"name": "A"}, question_order=["q4"])
    attempt.status = Attempt.Status.SUBMITTED
    attempt.save()
    full = text_of(render([attempt]))
    short = text_of(render([attempt], shorten=True))
    assert full.count("слово") == 100
    assert short.count("слово") < 50 and "…" in short


def test_hostile_text_does_not_break_rendering(sitting):
    nasty = "x" * 400 + "\x00\x07​ <b>&</b> \U0001f600 " + "\n" * 5 + "ы" * 300
    attempt = make_attempt(sitting, nasty[:60], {"q3": nasty, "q4": nasty})
    assert render([attempt]).startswith(b"%PDF")


def test_letter_paper_is_wider_than_a4_height(ivan):
    a4 = PdfReader(io.BytesIO(render([ivan], paper="A4"))).pages[0].mediabox
    letter = PdfReader(io.BytesIO(render([ivan], paper="Letter"))).pages[0].mediabox
    assert round(float(a4.width)) == 595 and round(float(letter.width)) == 612


# --- batch and size -------------------------------------------------------------------------


def test_batch_starts_each_sheet_on_a_new_page(sitting, ivan):
    other = make_attempt(sitting, "Олена Коваль", {"q1": ["a"]})
    reader = PdfReader(io.BytesIO(render([ivan, other])))
    assert len(reader.pages) == 2
    assert "Іван" in reader.pages[0].extract_text()
    assert "Олена" in reader.pages[1].extract_text()


def test_continuous_batch_saves_paper(sitting, ivan):
    other = make_attempt(sitting, "Олена Коваль", {"q1": ["a"]})
    reader = PdfReader(io.BytesIO(render([ivan, other], continuous=True)))
    assert len(reader.pages) == 1
    text = reader.pages[0].extract_text()
    assert "Іван" in text and "Олена" in text


def test_sizes_stay_small(sitting):
    attempts = [
        make_attempt(
            sitting,
            f"Учень {i}",
            {"q1": ["a"], "q2": ["a", "b"], "q3": "0.75", "q4": "відповідь " * 20},
        )
        for i in range(40)
    ]
    assert len(render(attempts[:1])) < 50 * 1024
    assert len(render(attempts)) < 1024 * 1024


def test_empty_batch_is_still_a_valid_pdf():
    assert render([]).startswith(b"%PDF")


# --- options from the query string ----------------------------------------------------------


def test_options_defaults_and_checkboxes():
    from django.http import QueryDict

    default = pdf.PdfOptions.from_query(QueryDict(""))
    assert default.show_correct and default.show_comments and default.mode == "compact"
    chosen = pdf.PdfOptions.from_query(QueryDict("opts=1&mode=full&paper=Letter&correct=on"))
    assert chosen.mode == "full" and chosen.paper == "Letter"
    assert chosen.show_correct and not chosen.show_comments and not chosen.continuous
    junk = pdf.PdfOptions.from_query(QueryDict("mode=evil&paper=A0"))
    assert junk.mode == "compact" and junk.paper == "A4"


# --- views ----------------------------------------------------------------------------------


def test_attempt_pdf_download(login, ivan):
    response = login.get(reverse("reports:attempt_pdf", args=[ivan.pk]))
    assert response.status_code == 200 and response["Content-Type"] == "application/pdf"
    disposition = response["Content-Disposition"]
    assert disposition.startswith("inline") and ".pdf" in disposition
    assert "%D0%B4%D1%80%D0%BE%D0%B1%D0%B8" in disposition  # "дроби", UTF-8 filename
    assert response.content.startswith(b"%PDF")


def test_attempt_pdf_options_apply(login, ivan):
    url = reverse("reports:attempt_pdf", args=[ivan.pk])
    plain = text_of(login.get(url).content)
    full = text_of(login.get(url, {"opts": "1", "mode": "full"}).content)
    assert "[x]" not in plain and "[x]" in full
    assert "Київ" in plain and "Київ" not in text_of(login.get(url, {"opts": "1"}).content)


def test_session_pdf_is_sorted_by_name_and_skips_unfinished(login, sitting, ivan):
    make_attempt(sitting, "Андрій", {"q1": ["a"]})
    make_attempt(sitting, "Хтось", {}, status=Attempt.Status.IN_PROGRESS)
    make_attempt(sitting, "Анулований", {}, status=Attempt.Status.VOIDED)
    response = login.get(reverse("reports:session_pdf", args=[sitting.pk]))
    text = text_of(response.content)
    assert response.status_code == 200 and "ABC234" in response["Content-Disposition"]
    assert text.index("Андрій") < text.index("Іван")
    assert "Хтось" not in text and "Анулований" not in text
    needs = text_of(
        login.get(
            reverse("reports:session_pdf", args=[sitting.pk]), {"status": "needs_review"}
        ).content
    )
    assert "Іван" in needs and "Андрій" not in needs


def test_permissions(client, sitting, ivan, django_user_model):
    urls = [
        reverse("reports:attempt_pdf", args=[ivan.pk]),
        reverse("reports:session_pdf", args=[sitting.pk]),
    ]
    for url in urls:
        response = client.get(url)
        assert response.status_code == 302 and "login" in response["Location"]
    client.force_login(django_user_model.objects.create_user("intruder", password="pw"))
    for url in urls:
        assert client.get(url).status_code == 404


def test_result_pages_link_to_pdf(login, sitting, ivan):
    sheet = login.get(reverse("reports:attempt", args=[ivan.pk])).content.decode()
    assert reverse("reports:attempt_pdf", args=[ivan.pk]) in sheet
    session = login.get(reverse("reports:session", args=[sitting.pk])).content.decode()
    assert reverse("reports:session_pdf", args=[sitting.pk]) in session
