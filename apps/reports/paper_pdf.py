"""The test as a printable PDF for a written (paper) test (F-07).

`render_paper(test, options)` returns the bytes of one PDF: a blank answer sheet per copy of each
chosen variant (title, the taker fields and the date as blanks, then every question with circles,
squares or ruled lines to write on), and, only when asked, an answer key at the end.

`test` is the normalised test of a valid document (`import_document(...).document["test"]`).
Questions keep the test's own order: there is no shuffling on paper. The labels follow the
test's language when it is Ukrainian or English (students read the paper), otherwise the
active UI language. Correct answers, accepted answers and rubrics are only ever read by the
answer-key part.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal

from django.utils import translation
from django.utils.formats import number_format
from django.utils.text import slugify
from django.utils.translation import gettext as _
from django.utils.translation import ngettext, pgettext
from fpdf import FPDF
from fpdf.enums import MethodReturnValue

from apps.exchange import variants as test_variants
from apps.exchange.document import CHOICE_TYPES

from .pdf import FONT, FONT_DIR, LINE, MARGIN, MUTED, PAPERS, clean

MAX_COPIES = 40
LABEL_LANGUAGES = ("uk", "en")
# Answer letters. Ukrainian tests skip the letters that are easy to confuse in handwriting.
UK_LETTERS = "АБВГДЕЄЖЗИІКЛМНОПРСТУФХЦЧШЩЮЯ"
EN_LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"

POINTS_WIDTH = 30  # mm, right column of a question title
INDENT = 6  # mm, options and answer lines under the title
MARK = 3.6  # mm, side of a square / diameter of a circle
MARK_GAP = 2.5  # mm between the mark and the letter
WRITE_LINE = 8.5  # mm between ruled lines (room for handwriting)
BLANK_ROW = 9  # mm, one row of header blanks
RULE_GRAY = (150, 150, 150)
GAP_AFTER_QUESTION = 4  # mm


@dataclass
class PaperOptions:
    variant: str = "all"  # "all" or the id of one variant
    copies: int = 1  # sheets per variant, each starting on a new page
    key: bool = False  # append the answer key
    paper: str = "A4"

    @classmethod
    def from_query(cls, query, variant_ids: list[str]) -> PaperOptions:
        """Read the options from a GET QueryDict. Anything unknown falls back to the default;
        the key is only printed when asked for (`key` present)."""
        options = cls()
        if query.get("variant") in variant_ids:
            options.variant = query["variant"]
        raw = str(query.get("copies") or "").strip()
        if raw.isascii() and raw.isdecimal() and len(raw) <= 3:
            options.copies = max(1, min(int(raw), MAX_COPIES))
        options.key = "key" in query and query.get("key") not in ("", "0")
        if query.get("paper") in PAPERS:
            options.paper = query["paper"]
        return options


class PaperPdf(FPDF):
    """Footer: "<label> · page n/N", numbered per section (one copy, or one variant's key),
    so every student's sheet starts at page 1."""

    footer_label = ""
    section_start = 1
    section_pages = 0  # 0 = not known (only while measuring)
    _pending: tuple[str, int] | None = None

    def start_section(self, label: str, pages: int) -> None:
        """The next page starts a section. It takes effect in header(), which FPDF calls once
        the new page exists, so the footer of the page before keeps the old section."""
        self._pending = (label, pages)

    def header(self):
        if self._pending is not None:
            self.footer_label, self.section_pages = self._pending
            self.section_start = self.page_no()
            self._pending = None

    def footer(self):
        self.set_y(-10)
        self.set_font(FONT, "", 8)
        self.set_text_color(*MUTED)
        page = self.page_no() - self.section_start + 1
        number = f"{_('page')} {page}" + (f"/{self.section_pages}" if self.section_pages else "")
        label = f"{self.footer_label} · " if self.footer_label else ""
        self.cell(0, 5, label + number, align="C")
        self.set_text_color(0, 0, 0)


def _new_pdf(paper: str) -> PaperPdf:
    pdf = PaperPdf(orientation="P", unit="mm", format=PAPERS[paper])
    pdf.set_margins(MARGIN, MARGIN, MARGIN)
    pdf.set_auto_page_break(True, margin=14)
    pdf.add_font(FONT, "", str(FONT_DIR / "DejaVuSans.ttf"))
    pdf.add_font(FONT, "B", str(FONT_DIR / "DejaVuSans-Bold.ttf"))
    return pdf


# ---------------------------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------------------------


def label_language(test: dict) -> str | None:
    """The language of the printed labels: the test's own when we have it, else None (keep
    the UI language)."""
    base = str(test.get("language") or "").split("-")[0].lower()
    return base if base in LABEL_LANGUAGES else None


def letters_for(test: dict) -> str:
    return UK_LETTERS if label_language(test) == "uk" else EN_LETTERS


def letter(letters: str, index: int) -> str:
    return letters[index] if index < len(letters) else str(index + 1)


def points_label(points) -> str:
    """ "(2 points)" in the active language; fractions read "(1.5 points)" / "(1,5 бала)"."""
    value = Decimal(str(points))
    if value == value.to_integral_value():
        n = int(value)
        return ngettext("(%(n)s point)", "(%(n)s points)", n) % {"n": n}
    shown = number_format(value.normalize(), use_l10n=True)
    return pgettext("fractional number of points", "(%(n)s points)") % {"n": shown}


def type_hint(question: dict) -> str:
    kind = question["type"]
    if kind == "single_choice":
        return _("Choose one answer.")
    if kind == "multiple_choice":
        return _("Select all that apply.")
    if kind == "choose_n":
        return _("Choose exactly %(n)s.") % {"n": question.get("n")}
    return ""


def open_lines(points) -> int:
    """Ruled lines for an open answer: 6, two more for every point from the third, at most 12."""
    value = float(points or 0)
    if value < 3:
        return 6
    return min(12, 6 + 2 * int(value - 2))


def _taker_labels(test: dict) -> list[tuple[str, str]]:
    """(key, label) of the blanks at the top: the test's taker fields, then the date."""
    labels = []
    for field in test.get("taker_fields") or []:
        key = str(field.get("key") or "")
        label = str(field.get("label") or key)
        if key == "name" and label == "Full name":  # the format's default label, in English
            label = _("Full name")
        labels.append((key, clean(label)))
    labels.append(("", _("Date")))
    return labels


def _lines(pdf: FPDF, width: float, text: str, height: float = LINE) -> int:
    if not text:
        return 1
    lines = pdf.multi_cell(
        width, height, text, dry_run=True, output=MethodReturnValue.LINES, align="L"
    )
    return len(lines) or 1


def _variants(test: dict, options: PaperOptions) -> list[tuple[dict, str]]:
    """(plain test, variant label) for every variant that is printed; one entry, with an empty
    label, for a test without variants."""
    ids = test_variants.variant_ids(test)
    if not ids:
        return [(test, "")]
    chosen = [options.variant] if options.variant in ids else ids
    return [(test_variants.view(test, v), test_variants.label(test, v)) for v in chosen]


# ---------------------------------------------------------------------------------------------
# The answer sheet
# ---------------------------------------------------------------------------------------------


def _header(pdf: PaperPdf, test: dict, variant_label: str) -> None:
    width = pdf.epw
    top = pdf.get_y()
    title_width = width - (45 if variant_label else 0)
    pdf.set_font(FONT, "B", 14)
    pdf.multi_cell(
        title_width, 6.5, clean(test.get("title", "")), new_x="LMARGIN", new_y="NEXT", align="L"
    )
    after_title = pdf.get_y()
    if variant_label:
        pdf.set_xy(pdf.l_margin + width - 45, top)
        pdf.set_font(FONT, "B", 12)
        pdf.multi_cell(45, 6.5, clean(variant_label), align="R", new_x="LMARGIN", new_y="NEXT")
        after_title = max(after_title, pdf.get_y())
    pdf.set_y(after_title + 3)

    # The blanks: a long line for the name, shorter ones for the rest, flowing over rows.
    pdf.set_font(FONT, "", 10)
    x, row_top = pdf.l_margin, pdf.get_y()
    right = pdf.l_margin + width
    for key, label in _taker_labels(test):
        text = f"{label}:"
        label_width = pdf.get_string_width(text) + 2
        blank = 85 if key == "name" else 38
        blank = min(blank, width - label_width)
        if x > pdf.l_margin and x + label_width + blank > right:
            x, row_top = pdf.l_margin, row_top + BLANK_ROW
        pdf.set_xy(x, row_top + BLANK_ROW - 7)
        pdf.cell(label_width, 6, text)
        baseline = row_top + BLANK_ROW - 1.5
        pdf.set_draw_color(*RULE_GRAY)
        pdf.set_line_width(0.25)
        pdf.line(x + label_width, baseline, x + label_width + blank, baseline)
        x += label_width + blank + 6
    pdf.set_draw_color(0, 0, 0)
    pdf.set_xy(pdf.l_margin, row_top + BLANK_ROW + 3)

    instructions = _instructions(test)
    if instructions:
        pdf.set_font(FONT, "", 9)
        pdf.set_text_color(*MUTED)
        pdf.multi_cell(width, 4.6, instructions, new_x="LMARGIN", new_y="NEXT", align="L")
        pdf.set_text_color(0, 0, 0)
    pdf.ln(1.5)
    pdf.set_draw_color(*RULE_GRAY)
    pdf.set_line_width(0.3)
    pdf.line(pdf.l_margin, pdf.get_y(), pdf.l_margin + width, pdf.get_y())
    pdf.set_draw_color(0, 0, 0)
    pdf.set_line_width(0.2)
    pdf.ln(4)


def _instructions(test: dict) -> str:
    kinds = {q["type"] for q in test.get("questions") or []}
    parts = []
    if "single_choice" in kinds:
        parts.append(_("○ – mark one answer"))
    if kinds & {"multiple_choice", "choose_n"}:
        parts.append(_("□ – mark as many as the question asks"))
    if kinds & {"short_answer", "open"}:
        parts.append(_("write other answers on the lines"))
    if not parts:
        return ""
    text = "; ".join(parts)
    return text[0].upper() + text[1:] + "."


def _option_rows(question: dict, letters: str) -> list[str]:
    return [
        f"{letter(letters, i)})  {clean(option.get('text', ''))}"
        for i, option in enumerate(question.get("options") or [])
    ]


def _question_height(pdf: PaperPdf, number: int, question: dict, letters: str) -> float:
    width = pdf.epw
    pdf.set_font(FONT, "B", 10.5)
    height = _lines(pdf, width - POINTS_WIDTH - 2, _title(number, question), 5) * 5 + 1
    pdf.set_font(FONT, "", 9)
    for note in _notes(question):
        height += _lines(pdf, width - INDENT, note, 4.4) * 4.4
    pdf.set_font(FONT, "", 10)
    option_width = width - INDENT - MARK - MARK_GAP
    if question["type"] in CHOICE_TYPES:
        for row in _option_rows(question, letters):
            height += _lines(pdf, option_width, row) * LINE + 1.6
    elif question["type"] == "short_answer":
        height += WRITE_LINE + 2
    else:
        height += open_lines(question.get("points")) * WRITE_LINE + 1
    return height + GAP_AFTER_QUESTION


def _title(number: int, question: dict) -> str:
    return f"{number}. {clean(question.get('text', '')).strip()}"


def _notes(question: dict) -> list[str]:
    notes = []
    if question.get("hint"):
        notes.append(clean(question["hint"]).strip())
    hint = type_hint(question)
    if hint:
        notes.append(hint)
    return notes


def _mark(pdf: PaperPdf, x: float, y: float, round_mark: bool) -> None:
    """An empty circle (one answer) or square (several) for the student to fill in."""
    pdf.set_draw_color(60, 60, 60)
    pdf.set_line_width(0.3)
    if round_mark:
        pdf.ellipse(x, y, MARK, MARK)
    else:
        pdf.rect(x, y, MARK, MARK)
    pdf.set_draw_color(0, 0, 0)
    pdf.set_line_width(0.2)


def _ruled(pdf: PaperPdf, x: float, count: int) -> None:
    pdf.set_draw_color(*RULE_GRAY)
    pdf.set_line_width(0.2)
    right = pdf.l_margin + pdf.epw
    for _i in range(count):
        y = pdf.get_y() + WRITE_LINE
        pdf.line(x, y, right, y)
        pdf.set_y(y)
    pdf.set_draw_color(0, 0, 0)


def _question(pdf: PaperPdf, number: int, question: dict, letters: str) -> None:
    width = pdf.epw
    height = _question_height(pdf, number, question, letters)
    room = pdf.h - pdf.b_margin - pdf.get_y()
    if height > room and height < pdf.h - pdf.t_margin - pdf.b_margin:
        pdf.add_page()

    x = pdf.l_margin
    top = pdf.get_y()
    pdf.set_font(FONT, "B", 10.5)
    pdf.multi_cell(
        width - POINTS_WIDTH - 2, 5, _title(number, question), new_x="LEFT", new_y="NEXT", align="L"
    )
    after_title = pdf.get_y()
    pdf.set_xy(x + width - POINTS_WIDTH, top)
    pdf.set_font(FONT, "", 9)
    pdf.set_text_color(*MUTED)
    pdf.multi_cell(POINTS_WIDTH, 5, points_label(question.get("points", 1)), align="R")
    pdf.set_text_color(0, 0, 0)
    pdf.set_xy(x, after_title + 1)

    pdf.set_font(FONT, "", 9)
    pdf.set_text_color(*MUTED)
    for note in _notes(question):
        pdf.set_x(x + INDENT)
        pdf.multi_cell(width - INDENT, 4.4, note, new_x="LEFT", new_y="NEXT", align="L")
    pdf.set_text_color(0, 0, 0)

    pdf.set_font(FONT, "", 10)
    if question["type"] in CHOICE_TYPES:
        round_mark = question["type"] == "single_choice"
        text_x = x + INDENT + MARK + MARK_GAP
        for row in _option_rows(question, letters):
            row_top = pdf.get_y() + 0.8
            _mark(pdf, x + INDENT, row_top + (LINE - MARK) / 2, round_mark)
            pdf.set_xy(text_x, row_top)
            pdf.multi_cell(
                width - INDENT - MARK - MARK_GAP, LINE, row, new_x="LEFT", new_y="NEXT", align="L"
            )
            pdf.set_y(pdf.get_y() + 0.8)
    elif question["type"] == "short_answer":
        label = f"{_('Answer')}:"
        pdf.set_xy(x + INDENT, pdf.get_y() + WRITE_LINE - LINE)
        pdf.cell(pdf.get_string_width(label) + 2, LINE, label)
        line_x = pdf.get_x()
        pdf.set_y(pdf.get_y() + LINE - WRITE_LINE)
        _ruled(pdf, line_x, 1)
        pdf.ln(2)
    else:
        _ruled(pdf, x + INDENT, open_lines(question.get("points")))
        pdf.ln(1)
    pdf.set_x(x)
    pdf.ln(GAP_AFTER_QUESTION)


def _draw_sheet(pdf: PaperPdf, test: dict, variant_label: str) -> None:
    pdf.add_page()
    _header(pdf, test, variant_label)
    letters = letters_for(test)
    for number, question in enumerate(test.get("questions") or [], start=1):
        _question(pdf, number, question, letters)


# ---------------------------------------------------------------------------------------------
# The answer key
# ---------------------------------------------------------------------------------------------


def _key_line(question: dict, letters: str) -> str:
    kind = question["type"]
    if kind in CHOICE_TYPES:
        options = question.get("options") or []
        right = [(letter(letters, i), o) for i, o in enumerate(options) if o.get("correct")]
        marks = ", ".join(mark for mark, _o in right)
        texts = "; ".join(clean(o.get("text", "")) for _m, o in right)
        return f"{marks}  ({texts})" if texts else marks
    if kind == "short_answer":
        accepted = "; ".join(clean(a) for a in question.get("accept") or [])
        return f"{_('Accepted answers')}: {accepted}"
    line = _("Open question: the teacher grades it.")
    if question.get("rubric"):
        line += f" {_('Rubric')}: {clean(question['rubric']).strip()}"
    return line


def _draw_key(pdf: PaperPdf, test: dict, variant_label: str) -> None:
    pdf.add_page()
    width = pdf.epw
    pdf.set_font(FONT, "B", 14)
    heading = _("Answer key")
    if variant_label:
        heading += f" · {clean(variant_label)}"
    pdf.multi_cell(width, 6.5, heading, new_x="LMARGIN", new_y="NEXT", align="L")
    pdf.set_font(FONT, "", 9)
    pdf.set_text_color(*MUTED)
    pdf.multi_cell(
        width, 4.6, clean(test.get("title", "")), new_x="LMARGIN", new_y="NEXT", align="L"
    )
    pdf.multi_cell(width, 4.6, _("For the teacher. Do not hand out."), new_x="LMARGIN", align="L")
    pdf.set_text_color(0, 0, 0)
    pdf.ln(3)

    letters = letters_for(test)
    number_width = 10
    for number, question in enumerate(test.get("questions") or [], start=1):
        line = _key_line(question, letters)
        points = points_label(question.get("points", 1))
        pdf.set_font(FONT, "", 10)
        height = _lines(pdf, width - number_width - POINTS_WIDTH, line) * LINE + 1.5
        if height > pdf.h - pdf.b_margin - pdf.get_y():
            pdf.add_page()
        top = pdf.get_y()
        pdf.set_font(FONT, "B", 10)
        pdf.cell(number_width, LINE, f"{number}.")
        pdf.set_font(FONT, "", 10)
        pdf.multi_cell(
            width - number_width - POINTS_WIDTH,
            LINE,
            line,
            new_x="LMARGIN",
            new_y="NEXT",
            align="L",
        )
        bottom = pdf.get_y()
        pdf.set_xy(pdf.l_margin + width - POINTS_WIDTH, top)
        pdf.set_font(FONT, "", 9)
        pdf.set_text_color(*MUTED)
        pdf.cell(POINTS_WIDTH, LINE, points, align="R")
        pdf.set_text_color(0, 0, 0)
        pdf.set_xy(pdf.l_margin, bottom + 1.5)


# ---------------------------------------------------------------------------------------------
# The whole file
# ---------------------------------------------------------------------------------------------


def _sections(test: dict, options: PaperOptions) -> list[tuple[str, Callable, int]]:
    """(footer label, draw function, copies) in print order."""
    title = clean(test.get("title", ""))
    sheets, keys = [], []
    for variant_test, variant_label in _variants(test, options):
        footer = f"{title} · {variant_label}" if variant_label else title

        def sheet(pdf, t=variant_test, v=variant_label):
            _draw_sheet(pdf, t, v)

        def key(pdf, t=variant_test, v=variant_label):
            _draw_key(pdf, t, v)

        sheets.append((footer[:90], sheet, options.copies))
        key_footer = f"{_('Answer key')} · {variant_label}" if variant_label else _("Answer key")
        keys.append((key_footer, key, 1))
    return sheets + (keys if options.key else [])


def _render(test: dict, options: PaperOptions) -> bytes:
    sections = _sections(test, options)
    # Pages per section, measured once on a scratch document, so the footer can say "page 1/2"
    # for every student's sheet (copies of one variant are identical).
    scratch = _new_pdf(options.paper)
    counts = []
    for _label, draw, _copies in sections:
        before = scratch.page_no()
        draw(scratch)
        counts.append(scratch.page_no() - before)

    pdf = _new_pdf(options.paper)
    pdf.set_title(clean(test.get("title", "")))
    pdf.set_creator("Knowledge Tester")
    for (label, draw, copies), pages in zip(sections, counts, strict=True):
        for _copy in range(copies):
            pdf.start_section(label, pages)
            draw(pdf)
    return bytes(pdf.output())


def render_paper(test: dict, options: PaperOptions | None = None) -> bytes:
    """The printable PDF. Labels in the test's language (uk / en), else the UI language."""
    options = options or PaperOptions()
    language = label_language(test)
    if language is None:
        return _render(test, options)
    with translation.override(language):
        return _render(test, options)


def filename(test: dict, options: PaperOptions) -> str:
    language = label_language(test)
    with translation.override(language or translation.get_language()):
        suffix = slugify(_("written test"), allow_unicode=True)
        variant = ""
        if options.variant != "all":
            variant = slugify(test_variants.label(test, options.variant), allow_unicode=True)
    title = slugify(test.get("title", ""), allow_unicode=True) or "test"
    return "_".join(p for p in (title[:80], variant, suffix) if p) + ".pdf"
