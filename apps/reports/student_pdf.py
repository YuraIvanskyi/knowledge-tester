"""One student's results as a PDF summary (plan §14, KT-605): fpdf2 plus the bundled DejaVu Sans.

Built like `apps.reports.pdf` (same fonts, footer, text cleaning): `render_student_pdf(profile)`
takes the `apps.people.profile.Profile` and returns the bytes. Labels follow the active UI
language; names and test titles are printed as stored. Long test names wrap inside their cell.
"""

from __future__ import annotations

from datetime import datetime

from django.utils import timezone
from django.utils.translation import gettext as _
from django.utils.translation import ngettext
from fpdf.fonts import FontFace

from . import pdf as sheets
from .templatetags.report_extras import grade_text, numd

TABLE_LINE = 4.6  # mm per table text line at 9 pt
SIZE = 9


def _percent(value, provisional: bool = False) -> str:
    if value is None:
        return "–"
    return f"{numd(value)} %" + (" *" if provisional else "")


def _score(row) -> str:
    if row.score is None:
        return "–"
    return f"{numd(row.score)} / {numd(row.max_score)}"


def _day(moment) -> str:
    return timezone.localtime(moment).strftime("%d.%m.%Y")


def _table(pdf, headings, rows, widths, aligns, styles=None) -> None:
    """A table with a bold heading row repeated on every page and wrapped cells.
    `styles` maps (row index, column index) to a FontFace for single cells."""
    styles = styles or {}
    pdf.set_font(sheets.FONT, "", SIZE)
    with pdf.table(
        col_widths=widths,
        text_align=aligns,
        line_height=TABLE_LINE,
        borders_layout="HORIZONTAL_LINES",
        headings_style=FontFace(emphasis="BOLD", color=sheets.MUTED),
        padding=(1, 1.2),
    ) as table:
        head = table.row()
        for text in headings:
            head.cell(text)
        for index, values in enumerate(rows):
            row = table.row()
            for column, text in enumerate(values):
                row.cell(sheets.clean(text), style=styles.get((index, column)))


def _heading(pdf, text: str) -> None:
    pdf.ln(3)
    pdf.set_font(sheets.FONT, "B", 11)
    pdf.cell(0, 6, text, new_x="LMARGIN", new_y="NEXT")
    pdf.ln(0.5)
    pdf.set_font(sheets.FONT, "", SIZE)


def _header(pdf, profile, generated: datetime) -> None:
    student = profile.student
    width = pdf.epw
    pdf.set_font(sheets.FONT, "", 9)
    pdf.set_text_color(*sheets.MUTED)
    pdf.cell(0, 4.6, _("Student results"), new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(0, 0, 0)
    pdf.set_font(sheets.FONT, "B", 15)
    pdf.multi_cell(width, 7, sheets.clean(student.full_name), new_x="LMARGIN", new_y="NEXT")

    group = student.group.name if student.group_id else _("No group")
    pdf.set_font(sheets.FONT, "", 9)
    pdf.set_text_color(*sheets.MUTED)
    stamp = timezone.localtime(generated).strftime("%d.%m.%Y %H:%M")
    pdf.multi_cell(
        width,
        4.6,
        f"{_('Group')}: {sheets.clean(group)} · {_('Generated')}: {stamp}",
        new_x="LMARGIN",
        new_y="NEXT",
    )
    pdf.set_text_color(0, 0, 0)
    pdf.ln(1)
    pdf.set_draw_color(150, 150, 150)
    pdf.line(pdf.l_margin, pdf.get_y(), pdf.l_margin + width, pdf.get_y())
    pdf.ln(1)


def _averages(pdf, profile) -> None:
    _heading(pdf, _("Averages"))
    if not profile.rows:
        pdf.set_text_color(*sheets.MUTED)
        pdf.cell(0, sheets.LINE, _("No finished results yet."), new_x="LMARGIN", new_y="NEXT")
        pdf.set_text_color(0, 0, 0)
        return

    overall = _percent(profile.overall_mean, profile.provisional)
    count = profile.overall_count
    pdf.set_font(sheets.FONT, "B", 11)
    pdf.cell(
        0,
        6,
        f"{_('Overall average')}: {overall}",
        new_x="LMARGIN",
        new_y="NEXT",
    )
    pdf.set_font(sheets.FONT, "", SIZE)
    pdf.set_text_color(*sheets.MUTED)
    pdf.cell(
        0,
        sheets.LINE,
        ngettext(
            "Mean of the percent of %(n)s counted attempt.",
            "Mean of the percent of %(n)s counted attempts.",
            count,
        )
        % {"n": count},
        new_x="LMARGIN",
        new_y="NEXT",
    )
    pdf.set_text_color(0, 0, 0)
    pdf.ln(1.5)

    rows = [
        (
            stats.title,
            str(stats.count),
            _percent(stats.mean, stats.provisional),
            _percent(stats.best),
            _percent(stats.latest),
        )
        for stats in profile.projects
    ]
    pending = FontFace(color=sheets.COLORS["pending"])
    styles = {(i, 2): pending for i, stats in enumerate(profile.projects) if stats.provisional}
    _table(
        pdf,
        [_("Project"), _("Attempts"), _("Average"), _("Best"), _("Latest")],
        rows,
        widths=(78, 22, 28, 28, 28),
        aligns=("LEFT", "RIGHT", "RIGHT", "RIGHT", "RIGHT"),
        styles=styles,
    )


def _history(pdf, profile) -> None:
    if not profile.rows:
        return
    _heading(pdf, _("History"))
    rows = []
    styles = {}
    for index, row in enumerate(profile.rows):
        session = row.session_title or row.session_code
        rows.append(
            (
                _day(row.when),
                row.test_title,
                f"{session} ({row.session_code})" if row.session_title else session,
                _score(row),
                _percent(row.percent, row.provisional),
                grade_text(row.grade) if row.grade else "–",
            )
        )
        if row.provisional:
            styles[(index, 4)] = FontFace(color=sheets.COLORS["pending"])
    _table(
        pdf,
        [_("Date"), _("Test"), _("Session"), _("Score"), _("Percent"), _("Grade")],
        rows,
        widths=(21, 59, 40, 22, 20, 18),
        aligns=("LEFT", "LEFT", "LEFT", "RIGHT", "RIGHT", "LEFT"),
        styles=styles,
    )


def _notes(pdf, profile, not_counted: str) -> None:
    pdf.ln(2)
    pdf.set_font(sheets.FONT, "", 8.5)
    pdf.set_text_color(*sheets.MUTED)
    if profile.provisional:
        pdf.set_text_color(*sheets.COLORS["pending"])
        pdf.multi_cell(
            pdf.epw,
            4.4,
            "* " + _("Provisional: some answers still need review."),
            new_x="LMARGIN",
            new_y="NEXT",
        )
        pdf.set_text_color(*sheets.MUTED)
    if not_counted:
        pdf.multi_cell(pdf.epw, 4.4, not_counted, new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(0, 0, 0)


def render_student_pdf(
    profile, *, paper: str = "A4", generated: datetime | None = None, not_counted: str = ""
) -> bytes:
    """The summary of `profile` as PDF bytes. `not_counted` is the one-line note about attempts
    that are left out (see `apps.people.profile.not_counted_text`)."""
    if paper not in sheets.PAPERS:
        paper = "A4"
    student = profile.student
    pdf = sheets.SheetPdf(orientation="P", unit="mm", format=sheets.PAPERS[paper])
    pdf.set_margins(sheets.MARGIN, sheets.MARGIN, sheets.MARGIN)
    pdf.set_auto_page_break(True, margin=14)
    pdf.add_font(sheets.FONT, "", str(sheets.FONT_DIR / "DejaVuSans.ttf"))
    pdf.add_font(sheets.FONT, "B", str(sheets.FONT_DIR / "DejaVuSans-Bold.ttf"))
    pdf.alias_nb_pages()
    pdf.set_title(sheets.clean(student.full_name))
    pdf.set_creator("Knowledge Tester")
    pdf.footer_text = sheets.clean(student.full_name)
    pdf.add_page()
    _header(pdf, profile, generated or timezone.now())
    _averages(pdf, profile)
    _history(pdf, profile)
    _notes(pdf, profile, not_counted)
    return bytes(pdf.output())
