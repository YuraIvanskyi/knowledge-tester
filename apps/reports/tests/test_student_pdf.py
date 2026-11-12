"""Student summary PDF: Cyrillic text, wrapping, provisional marks, paper, size and speed.

No database: the profile is assembled from in-memory rows (`profile_from_rows`)."""

import io
import time
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from django.utils import translation
from pypdf import PdfReader

from apps.people.models import Group, Student
from apps.people.profile import HistoryRow, not_counted_text, profile_from_rows
from apps.reports import student_pdf

BASE = datetime(2026, 9, 1, 9, 0, tzinfo=UTC)
GENERATED = datetime(2026, 11, 12, 14, 5, tzinfo=UTC)


def student(name="Іваненко Петро", group="7-А"):
    return Student(pk=7, full_name=name, group=Group(pk=3, name=group) if group else None)


def row(
    i=0, *, percent="80.0", kind="counted", pending=0, test="Дроби", project="Математика", **kw
):
    score = None if percent is None else Decimal(percent) / 10
    values = dict(
        attempt_id=i + 1,
        kind=kind,
        status={"counted": "submitted", "voided": "voided", "in_progress": "in_progress"}.get(
            kind, "submitted"
        ),
        when=BASE + timedelta(days=i),
        test_title=test,
        project_id=hash(project) % 1000,
        project_title=project,
        session_id=1,
        session_title="Контрольна",
        session_code="ABC234",
        score=score,
        max_score=Decimal("10") if score is not None else None,
        percent=None if percent is None else Decimal(percent),
        grade="",
        pending_reviews=pending,
    )
    values.update(kw)
    return HistoryRow(**values)


def render(rows, who=None, language="en", **options):
    profile = profile_from_rows(who or student(), rows)
    with translation.override(language):
        return student_pdf.render_student_pdf(
            profile,
            generated=GENERATED,
            not_counted=not_counted_text(profile),
            **options,
        )


def pages(content: bytes) -> list[str]:
    return [page.extract_text() for page in PdfReader(io.BytesIO(content)).pages]


def text_of(content: bytes) -> str:
    return "\n".join(pages(content))


def test_header_has_name_group_date_and_ukrainian_text():
    text = text_of(render([row(0, percent="70.0", grade="3"), row(1, percent="90.0", grade="5")]))
    for expected in ("Student results", "Іваненко Петро", "7-А", "12.11.2026 14:05"):
        assert expected in text, expected
    assert "Дроби" in text and "Математика" in text and "Контрольна" in text
    assert "ABC234" in text
    assert "01.09.2026" in text and "02.09.2026" in text


def test_it_renders_in_ukrainian_too():
    content = render([row()], language="uk")
    assert content.startswith(b"%PDF")
    assert "Іваненко Петро" in text_of(content)


def test_averages_are_printed_per_project_and_overall():
    rows = [
        row(1, percent="70.0", project="Математика"),
        row(2, percent="85.5", project="Математика"),
        row(3, percent="40.0", project="Фізика", test="Рух"),
    ]
    text = text_of(render(rows))
    assert "Overall average: 65.2 %" in text  # (70 + 85.5 + 40) / 3
    assert "Mean of the percent of 3 counted attempts." in text
    assert "Математика 2 77.8 % 85.5 % 85.5 %" in text  # attempts, mean, best, latest
    assert "Фізика 1 40 % 40 % 40 %" in text
    assert text.index("Математика 2") < text.index("Фізика 1")


def test_long_test_names_wrap_instead_of_overflowing():
    title = " ".join(["довга-назва-тесту"] * 30)
    content = render([row(0, test=title)])
    text = text_of(content)
    assert text.count("довга-назва-тесту") == 30  # nothing cut
    reader = PdfReader(io.BytesIO(content))
    assert len(reader.pages) == 1


def test_an_unbroken_very_long_word_does_not_crash():
    content = render([row(0, test="Я" * 400, project="П" * 300)])
    assert content.startswith(b"%PDF")


def test_provisional_results_are_marked_and_explained():
    plain = text_of(render([row(0, percent="70.0")]))
    assert "Provisional" not in plain and "*" not in plain
    marked = text_of(render([row(0, percent="70.0"), row(1, percent="80.0", pending=2)]))
    assert "* Provisional: some answers still need review." in marked
    assert marked.count(" *") >= 3  # overall, project row, history row


def test_attempts_that_do_not_count_are_summarised_not_listed():
    rows = [
        row(0, percent="70.0"),
        row(1, kind="voided", test="Анульований тест"),
        row(2, kind="in_progress", test="Ще триває", percent=None),
    ]
    text = text_of(render(rows))
    assert "Not counted: 1 attempt in progress; 1 voided attempt" in text
    assert "Анульований тест" not in text and "Ще триває" not in text


def test_a_student_without_results():
    text = text_of(render([]))
    assert "Іваненко Петро" in text and "No finished results yet." in text
    assert "History" not in text


def test_a_student_without_group_or_with_an_awkward_name():
    text = text_of(render([row()], who=student("Дем’ян О'Коннор-Шевченко", group=None)))
    assert "No group" in text and "Дем’ян О'Коннор-Шевченко" in text


def test_hostile_text_does_not_break_rendering():
    nasty = "x" * 300 + "\x00\x07 <b>&</b> \U0001f600 \n\n" + "ы" * 100
    content = render([row(0, test=nasty, project=nasty)], who=student(nasty[:80], group=nasty))
    assert content.startswith(b"%PDF")


def test_paper_sizes():
    a4 = PdfReader(io.BytesIO(render([row()]))).pages[0].mediabox
    letter = PdfReader(io.BytesIO(render([row()], paper="Letter"))).pages[0].mediabox
    junk = PdfReader(io.BytesIO(render([row()], paper="A0"))).pages[0].mediabox
    assert round(float(a4.width)) == 595 and round(float(letter.width)) == 612
    assert round(float(junk.width)) == 595


def test_forty_attempts_stay_small_and_fast():
    rows = [
        row(
            i,
            percent=str(40 + i),
            pending=1 if i % 9 == 0 else 0,
            test=f"Контрольна робота номер {i} з української літератури: основи",
            project="Математика" if i % 2 else "Українська мова",
        )
        for i in range(40)
    ]
    started = time.perf_counter()
    content = render(rows)
    elapsed = time.perf_counter() - started
    assert len(content) < 200 * 1024
    assert elapsed < 2.0
    sheets = pages(content)
    assert len(sheets) >= 2
    full = "\n".join(sheets)
    assert full.count("ABC234") == 40  # every attempt listed once
    assert "Контрольна робота номер 39" in full


def test_page_footer_has_the_name_and_page_numbers():
    rows = [row(i, percent=str(30 + i)) for i in range(60)]
    sheets = pages(render(rows))
    assert len(sheets) >= 2
    assert "Іваненко Петро" in sheets[0] and "page 1/" in sheets[0]
    assert f"page {len(sheets)}/{len(sheets)}" in sheets[-1]


def test_the_table_heading_is_repeated_on_every_page():
    rows = [row(i, percent=str(30 + i)) for i in range(60)]
    sheets = pages(render(rows))
    assert len(sheets) >= 2
    assert all("Date" in page and "Percent" in page for page in sheets[1:])
