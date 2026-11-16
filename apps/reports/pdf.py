"""Lean PDF sheets of results (plan §13.3, ADR-0005): fpdf2 plus a bundled DejaVu Sans.

`render_pdf(attempts, options)` returns the bytes of one PDF with a sheet per attempt. Attempts
should come with `select_related("sitting__revision__assessment")` and
`prefetch_related("answers")`.
The text uses the active UI language (labels) and the stored taker data and test content as is.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from django.conf import settings
from django.utils import timezone
from django.utils.text import slugify
from django.utils.translation import gettext as _
from fpdf import FPDF
from fpdf.enums import MethodReturnValue

from apps.exchange.document import CHOICE_TYPES

from . import data
from .templatetags.report_extras import grade_text, numd

FONT_DIR = settings.BASE_DIR / "assets" / "fonts"
FONT = "DejaVu"
MARGIN = 12
LINE = 4.8  # mm per text line at 10 pt
INDENT = 5
POINTS_WIDTH = 54
SHORTEN_AT = 200
_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")

PAPERS = {"A4": "A4", "Letter": "Letter"}
MODES = ("compact", "full")

COLORS = {
    "correct": (0, 110, 40),
    "partial": (150, 90, 0),
    "pending": (150, 90, 0),
    "wrong": (170, 0, 0),
}
MUTED = (95, 95, 95)


@dataclass
class PdfOptions:
    mode: str = "compact"  # "compact": chosen answers only; "full": every option
    paper: str = "A4"
    show_correct: bool = True
    show_comments: bool = True
    show_unanswered: bool = True
    shorten: bool = False  # cut long question text
    continuous: bool = False  # batch: do not start a new page for every sheet

    @classmethod
    def from_query(cls, query) -> PdfOptions:
        """Read options from a GET QueryDict. Without `opts=1` everything is the default;
        with it, a missing checkbox means off (browsers omit unchecked boxes)."""
        options = cls()
        mode = query.get("mode")
        if mode in MODES:
            options.mode = mode
        if query.get("paper") in PAPERS:
            options.paper = query["paper"]
        if query.get("opts"):
            options.show_correct = "correct" in query
            options.show_comments = "comments" in query
            options.show_unanswered = "unanswered" in query
            options.shorten = "shorten" in query
            options.continuous = "continuous" in query
        return options


class SheetPdf(FPDF):
    footer_text = ""

    def footer(self):
        self.set_y(-10)
        self.set_font(FONT, "", 8)
        self.set_text_color(*MUTED)
        label = f"{self.footer_text} · " if self.footer_text else ""
        self.cell(0, 5, f"{label}{_('page')} {self.page_no()}/{{nb}}", align="C")
        self.set_text_color(0, 0, 0)


def clean(value: object) -> str:
    """Printable text: no control characters; tabs become spaces."""
    text = "" if value is None else str(value)
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\t", "    ")
    return _CONTROL.sub("", text)


def attempt_code(attempt) -> str:
    return str(attempt.token)[:4].upper()


def _lines(pdf: FPDF, width: float, text: str) -> int:
    if not text:
        return 1
    return len(pdf.multi_cell(width, LINE, text, dry_run=True, output=MethodReturnValue.LINES)) or 1


def _taker_pairs(test: dict, attempt) -> list[tuple[str, str]]:
    taker = attempt.taker or {}
    pairs, seen = [], set()
    for field in test.get("taker_fields", []):
        key = field.get("key")
        seen.add(key)
        pairs.append((field.get("label") or key, str(taker.get(key, ""))))
    pairs += [(k, str(v)) for k, v in taker.items() if k not in seen]
    if attempt.variant_label:
        pairs.append((_("Variant"), attempt.variant_label))
    return pairs


def _local(moment) -> str:
    return timezone.localtime(moment).strftime("%d.%m.%Y %H:%M")


# ---------------------------------------------------------------------------------------------
# One sheet
# ---------------------------------------------------------------------------------------------


def _header(pdf: SheetPdf, attempt, test: dict, grading_enabled: bool) -> None:
    sitting = attempt.sitting
    width = pdf.epw
    pdf.set_font(FONT, "B", 14)
    pdf.multi_cell(width, 6.5, clean(test.get("title", "")), new_x="LMARGIN", new_y="NEXT")
    pdf.set_font(FONT, "", 9)
    pdf.set_text_color(*MUTED)
    sub = " · ".join(
        [
            clean(sitting.title or test.get("title", "")),
            f"{_('revision')} {sitting.revision.number}",
            f"{_('session')} {sitting.code}",
        ]
    )
    pdf.multi_cell(width, 4.6, sub, new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(0, 0, 0)
    pdf.ln(1.5)

    pdf.set_font(FONT, "", 10)
    for label, value in _taker_pairs(test, attempt):
        pdf.set_font(FONT, "B", 10)
        pdf.write(LINE, f"{clean(label)}: ")
        pdf.set_font(FONT, "", 10)
        pdf.write(LINE, clean(value) or "-")
        pdf.ln(LINE)
    if attempt.submitted_at:
        pdf.set_font(FONT, "B", 10)
        pdf.write(LINE, f"{_('Submitted')}: ")
        pdf.set_font(FONT, "", 10)
        pdf.write(LINE, _local(attempt.submitted_at))
        pdf.ln(LINE)

    pdf.ln(1)
    if not grading_enabled:
        pdf.set_text_color(*MUTED)
        pdf.multi_cell(width, LINE, _("Grading is disabled for this test."), new_x="LMARGIN")
        pdf.set_text_color(0, 0, 0)
    elif attempt.score is None:
        pdf.set_text_color(*MUTED)
        pdf.multi_cell(width, LINE, _("Not graded yet."), new_x="LMARGIN", new_y="NEXT")
        pdf.set_text_color(0, 0, 0)
    else:
        score = f"{numd(attempt.score)} / {numd(attempt.max_score)}"
        if attempt.percent is not None:
            score += f" ({numd(attempt.percent)} %)"
        text = f"{_('Score')}: {score}"
        if attempt.grade:
            text += f"    {_('Grade')}: {clean(grade_text(attempt.grade))}"
        pdf.set_font(FONT, "B", 11)
        pdf.multi_cell(width, 5.6, text, new_x="LMARGIN", new_y="NEXT")
        if attempt.pending_reviews:
            pdf.set_font(FONT, "", 9)
            pdf.set_text_color(*COLORS["pending"])
            pdf.multi_cell(
                width,
                4.6,
                _("Provisional: some answers still need review."),
                new_x="LMARGIN",
                new_y="NEXT",
            )
            pdf.set_text_color(0, 0, 0)
    pdf.ln(1.5)
    pdf.set_draw_color(150, 150, 150)
    pdf.line(pdf.l_margin, pdf.get_y(), pdf.l_margin + width, pdf.get_y())
    pdf.ln(2.5)


def _body_items(row, attempt, options: PdfOptions) -> list[tuple[str, str]]:
    """(kind, text) lines under a question. kind: answer | option | correct | comment | none."""
    question = row.question
    items: list[tuple[str, str]] = []
    show_correct = options.show_correct and row.marker != "correct"

    if options.mode == "full" and question["type"] in CHOICE_TYPES:
        value = row.answer.value if row.answer else None
        chosen = {value} if isinstance(value, str) else set(value or [])
        by_id = {o["id"]: o for o in question.get("options", [])}
        order = [i for i in attempt.option_orders.get(str(question["id"]), []) if i in by_id]
        order += [i for i in by_id if i not in order]
        for option_id in order:
            option = by_id[option_id]
            mark = "[x]" if option_id in chosen else "[ ]"
            tick = "  ✓" if options.show_correct and option.get("correct") else ""
            items.append(("option", f"{mark} {clean(option['text'])}{tick}"))
        if not chosen:
            items.append(("none", _("No answer")))
    else:
        if row.selected:
            items.append(("answer", f"{_('Answer')}: " + "; ".join(clean(s) for s in row.selected)))
        elif row.text_answer.strip():
            items.append(("answer", f"{_('Answer')}: {clean(row.text_answer).strip()}"))
        else:
            items.append(("none", _("No answer")))
        if show_correct and row.correct:
            label = _("Accepted answers") if question["type"] == "short_answer" else _("Correct")
            items.append(("correct", f"{label}: " + "; ".join(clean(c) for c in row.correct)))

    feedback = (row.answer.feedback if row.answer else "") or ""
    if options.show_comments and feedback.strip():
        items.append(("comment", f"{_('Comment')}: {clean(feedback).strip()}"))
    return items


def _points_text(row, grading_enabled: bool) -> str:
    if not grading_enabled or not row.max_points:
        return row.marker_label if row.marker != "ungraded" else ""
    return f"{numd(row.points)} / {numd(row.max_points)} · {row.marker_label}"


def _question(pdf: SheetPdf, row, attempt, options: PdfOptions, grading_enabled: bool) -> None:
    width = pdf.epw
    text_width = width - POINTS_WIDTH - 2
    body_width = width - INDENT
    question_text = clean(row.question["text"]).strip()
    if options.shorten and len(question_text) > SHORTEN_AT:
        question_text = question_text[: SHORTEN_AT - 1].rstrip() + "…"
    title = f"{row.number}. {question_text}"
    items = _body_items(row, attempt, options)

    pdf.set_font(FONT, "B", 10)
    height = _lines(pdf, text_width, title) * LINE
    pdf.set_font(FONT, "", 10)
    height += sum(_lines(pdf, body_width, text) * LINE for _kind, text in items) + 2.5
    # Keep a question together on one page unless it is taller than a page.
    room = pdf.h - pdf.b_margin - pdf.get_y()
    if height > room and height < pdf.h - pdf.t_margin - pdf.b_margin:
        pdf.add_page()

    top = pdf.get_y()
    x = pdf.l_margin
    pdf.set_font(FONT, "B", 10)
    pdf.multi_cell(text_width, LINE, title, new_x="LEFT", new_y="NEXT")
    after_title = pdf.get_y()
    marker_text = _points_text(row, grading_enabled)
    if marker_text:
        pdf.set_xy(x + width - POINTS_WIDTH, top)
        pdf.set_font(FONT, "", 9)
        pdf.set_text_color(*COLORS.get(row.marker, MUTED))
        pdf.multi_cell(POINTS_WIDTH, LINE, marker_text, align="R", new_x="LEFT", new_y="NEXT")
        pdf.set_text_color(0, 0, 0)
        after_title = max(after_title, pdf.get_y())
    pdf.set_xy(x, after_title)

    pdf.set_font(FONT, "", 10)
    for kind, text in items:
        pdf.set_x(x + INDENT)
        if kind in ("none", "comment"):
            pdf.set_text_color(*MUTED)
        elif kind == "correct":
            pdf.set_text_color(*COLORS["correct"])
        pdf.multi_cell(body_width, LINE, text, new_x="LEFT", new_y="NEXT")
        pdf.set_text_color(0, 0, 0)
    pdf.set_x(x)
    pdf.ln(2.5)


def _sheet(pdf: SheetPdf, attempt, options: PdfOptions, *, first: bool) -> None:
    sitting = attempt.sitting
    test = attempt.test  # the attempt's variant
    grading_enabled = (test.get("grading") or {}).get("enabled", True)
    rows = data.build_sheet(attempt, test, list(attempt.answers.all()))

    if first or not options.continuous or pdf.get_y() > pdf.h - pdf.b_margin - 60:
        pdf.add_page()
    else:
        pdf.ln(6)
    pdf.footer_text = (
        sitting.code
        if options.continuous
        else f"{_('Attempt')} {attempt_code(attempt)} · {clean(data.taker_name(attempt))}"
    )
    _header(pdf, attempt, test, grading_enabled)
    for row in rows:
        if row.marker == "unanswered" and not options.show_unanswered:
            continue
        _question(pdf, row, attempt, options, grading_enabled)


def render_pdf(attempts: list, options: PdfOptions | None = None) -> bytes:
    options = options or PdfOptions()
    pdf = SheetPdf(orientation="P", unit="mm", format=PAPERS[options.paper])
    pdf.set_margins(MARGIN, MARGIN, MARGIN)
    pdf.set_auto_page_break(True, margin=14)
    pdf.add_font(FONT, "", str(FONT_DIR / "DejaVuSans.ttf"))
    pdf.add_font(FONT, "B", str(FONT_DIR / "DejaVuSans-Bold.ttf"))
    pdf.alias_nb_pages()
    pdf.set_title(clean(attempts[0].sitting.revision.test.get("title", "")) if attempts else "")
    pdf.set_creator("Knowledge Tester")
    for index, attempt in enumerate(attempts):
        _sheet(pdf, attempt, options, first=index == 0)
    if not attempts:
        pdf.add_page()
        pdf.set_font(FONT, "", 10)
        pdf.cell(0, LINE, _("No attempts yet."))
    return bytes(pdf.output())


# ---------------------------------------------------------------------------------------------
# File names
# ---------------------------------------------------------------------------------------------


def attempt_filename(attempt) -> str:
    test = attempt.sitting.revision.test
    parts = [slugify(test.get("title", ""), allow_unicode=True) or "test"]
    taker = attempt.taker or {}
    for key in ("class", "group", "klas"):
        if taker.get(key):
            parts.append(slugify(str(taker[key]), allow_unicode=True))
            break
    parts.append(slugify(data.taker_name(attempt), allow_unicode=True) or attempt_code(attempt))
    return "_".join(p for p in parts if p)[:120] + ".pdf"


def session_filename(sitting) -> str:
    title = slugify(sitting.revision.test.get("title", ""), allow_unicode=True) or "test"
    return f"{title}_{sitting.code}.pdf"
