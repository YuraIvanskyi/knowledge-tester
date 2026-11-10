# ADR-0005: fpdf2 for PDF sheets

- **Status:** Proposed (2026-11-10)
- **Related:** plan.md §13.3 · KT-501–KT-503

## Context

Results must print as *lean* PDFs: one sheet per attempt, or a whole session in one file. The text includes Cyrillic. The host is Windows, and installation must stay simple, using only pip/uv packages.

## Decision

- Generate PDFs on the server with **fpdf2**, which is pure Python and pulls in fontTools for subsetting.
- Bundle one Unicode TTF family covering Latin, Cyrillic and every symbol we print (DejaVu Sans or Noto Sans; chosen in KT-501 after a glyph check) in `assets/fonts/`, embedded as a subset.
- Build the layout in code: a header block, a compact question/answer list and a footer with page numbers.
- In addition, a **print stylesheet** on the HTML sheet view allows plain browser printing as a zero-dependency fallback.

## Consequences

- **Easier:** no system libraries are needed. Files are small (targets: 50 KB or less per sheet, 1 MB or less per 40-sheet batch). Generation is fast and deterministic, and the output is easy to test.
- **Harder:** the layout is written in Python rather than HTML/CSS, so complex designs take more code. Sheets are intentionally simple, so that's acceptable.

## Alternatives considered

- **WeasyPrint:** the best HTML/CSS fidelity, but it needs GTK/Pango on Windows, which is painful to install for a teacher.
- **xhtml2pdf:** pure Python, but has limited and quirky CSS support.
- **ReportLab:** powerful but more verbose, and the fpdf2 API is enough here.
- **Browser print only:** no batch export, and the output varies from browser to browser. Kept only as a fallback.
