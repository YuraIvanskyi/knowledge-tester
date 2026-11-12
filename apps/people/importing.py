"""Reading a class list the teacher pasted or uploaded (KT-602).

Pure Python: no database, no request. Every parser returns a list of `ParsedRow` and raises
`RosterImportError` (with a message meant for the teacher) when the input cannot be read at all.
Problems with a single row are not errors: they are recorded in `ParsedRow.issues` and shown in
the import preview, where the teacher decides what to do.

Public entry points (the Phase 7 LLM import reuses them and `services.build_preview`):

    parse_text(text)    one name per line, optional `Name; Group` / `Name, Group` / tab-separated
    parse_csv(data)     CSV bytes: delimiter, encoding and header columns are detected
    parse_xlsx(data)    XLSX bytes through openpyxl (optional extra), values only, no formulas
    parse_file(data)    sniffs the content (file names are never trusted) and picks one of the two
"""

from __future__ import annotations

import csv
import io
import re
import unicodedata
import zipfile
from collections import Counter
from dataclasses import dataclass, field

from django.utils.translation import gettext_lazy as _

from .names import normalize_name

MAX_BYTES = 2 * 1024 * 1024
MAX_ROWS = 2000
MAX_NAME_LENGTH = 200  # Student.full_name
MAX_GROUP_LENGTH = 200  # Group.name
MAX_COLUMNS = 12
# An XLSX is a zip: refuse archives that would inflate to something absurd.
MAX_XLSX_UNPACKED = 60 * 1024 * 1024
MAX_XLSX_SCANNED_ROWS = 20_000

ISSUE_EMPTY = "empty"
ISSUE_TOO_LONG = "too_long"
ISSUE_NO_LETTERS = "no_letters"
ISSUE_GROUP_TOO_LONG = "group_too_long"
ISSUE_BAD_GROUP = "bad_group"

ISSUE_LABELS = {
    ISSUE_EMPTY: _("the name is empty"),
    ISSUE_TOO_LONG: _("the name is too long"),
    ISSUE_NO_LETTERS: _("the name has no letters"),
    ISSUE_GROUP_TOO_LONG: _("the group name is too long"),
    ISSUE_BAD_GROUP: _("the group name has no letters or digits"),
}


class RosterImportError(ValueError):
    """The input cannot be read at all. `str(error)` is a plain message for the teacher."""


@dataclass
class ParsedRow:
    full_name: str
    group_name: str = ""
    issues: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"n": self.full_name, "g": self.group_name, "i": list(self.issues)}

    @classmethod
    def from_dict(cls, data: dict) -> ParsedRow:
        issues = data.get("i") or []
        return cls(
            full_name=str(data.get("n") or ""),
            group_name=str(data.get("g") or ""),
            issues=[str(item) for item in issues if isinstance(item, str)],
        )


# ---- cleaning -----------------------------------------------------------------------------


def clean(value) -> str:
    """One tidy line: NFC, no invisible or control characters, single spaces."""
    text = unicodedata.normalize("NFC", "" if value is None else str(value))
    out = []
    for ch in text:
        category = unicodedata.category(ch)
        if category == "Cf":  # zero-width space, BOM, soft hyphen, bidi marks
            continue
        out.append(" " if category in ("Cc", "Zl", "Zp") else ch)
    return " ".join("".join(out).split())


# A list marker in front of a name: "1.", "2)", "(3)", "4 -", "- ", "* ", bullets.
_MARKER = re.compile(
    r"^(?:"
    r"[-–—*•·▪●○]+\s+"  # dash or bullet and a space
    r"|[•·▪●○*]+"  # bullet glued to the name
    r"|\(?\d{1,4}[.)]\s*"  # 1.  2)  (3)
    r"|\d{1,4}\s+[-–—]\s+"  # 4 - name
    r")"
)
_QUOTES = '"«»“”„'


def strip_marker(text: str) -> str:
    for _attempt in range(3):
        stripped = _MARKER.sub("", text, count=1).strip()
        if stripped == text:
            break
        text = stripped
    return text


def issues_for(full_name: str, group_name: str) -> list[str]:
    """What is wrong with one (already cleaned) name and group; empty list = fine."""
    issues = []
    if not full_name:
        issues.append(ISSUE_EMPTY)
    else:
        if len(full_name) > MAX_NAME_LENGTH:
            issues.append(ISSUE_TOO_LONG)
        if not any(ch.isalpha() for ch in full_name):
            issues.append(ISSUE_NO_LETTERS)
    if group_name:
        if len(group_name) > MAX_GROUP_LENGTH:
            issues.append(ISSUE_GROUP_TOO_LONG)
        elif not normalize_name(group_name):
            issues.append(ISSUE_BAD_GROUP)
    return issues


def make_row(full_name, group_name="") -> ParsedRow | None:
    """A cleaned row with its issues, or None when there is nothing in it."""
    name = strip_marker(clean(full_name)).strip(_QUOTES).strip()
    group = clean(group_name).strip(_QUOTES).strip()
    if not name and not group:
        return None
    return ParsedRow(name, group, issues_for(name, group))


def _has_digit(text: str) -> bool:
    return any(ch.isdigit() for ch in text)


def _name_and_group(cells: list[str]) -> tuple[str, str]:
    """Split the cells of a headerless line into a name and an optional group.

    The last cell is a group when it contains a digit ("7-A", "10 клас") or when the cell
    before it is already a full name of two or more words ("Іван Петренко; Alpha").
    Otherwise all cells are parts of the name: "Іваненко, Петро" is one person.
    """
    cells = [cell for cell in (clean(c) for c in cells) if cell]
    if not cells:
        return "", ""
    if len(cells) == 1:
        return cells[0], ""
    last = cells[-1]
    if _has_digit(last) or (len(cells) == 2 and len(cells[0].split()) >= 2):
        return " ".join(cells[:-1]), last
    return " ".join(cells), ""


# ---- header detection ---------------------------------------------------------------------

_HEADER_WORDS = {
    "name": {
        "name",
        "full name",
        "fullname",
        "student",
        "student name",
        "students",
        "піб",
        "фіо",
        "фио",
        "учень",
        "учні",
        "ученик",
        "прізвище ім'я по батькові",
        "прізвище та ім'я",
        "прізвище ім'я",
        "прізвище і ім'я",
    },
    "surname": {"surname", "last name", "lastname", "family name", "прізвище", "фамилия"},
    "first": {"first name", "firstname", "given name", "ім'я", "імя", "имя"},
    "middle": {"patronymic", "middle name", "по батькові", "по-батькові", "отчество"},
    "group": {"group", "class", "form", "клас", "група", "класс", "группа"},
    "index": {"№", "#", "no", "n", "num", "number", "nr", "п п", "№ п п", "номер"},
}
_ROLE_OF_WORD = {word: role for role, words in _HEADER_WORDS.items() for word in words}


def _header_role(cell: str) -> str | None:
    key = normalize_name(cell) or cell.strip()
    return _ROLE_OF_WORD.get(key)


def _find_header(cells: list[str]) -> dict[str, list[int]] | None:
    """Column indexes by role if this row is a header row (it names a name column)."""
    columns: dict[str, list[int]] = {}
    for index, cell in enumerate(cells):
        role = _header_role(cell)
        if role:
            columns.setdefault(role, []).append(index)
    if not any(role in columns for role in ("name", "surname", "first")):
        return None
    return columns


def _is_header_line(cells: list[str]) -> bool:
    """A pasted first line that only holds header words ("ПІБ; Клас")."""
    cleaned = [clean(cell) for cell in cells if clean(cell)]
    return (
        bool(cleaned)
        and all(_header_role(cell) for cell in cleaned)
        and _find_header(cleaned) is not None
    )


# ---- tables (CSV, XLSX and pasted tables with a header) -----------------------------------


def _table_to_rows(table: list[list]) -> list[ParsedRow]:
    table = [[clean(cell) for cell in row[:MAX_COLUMNS]] for row in table]
    table = [row for row in table if any(row)]
    if not table:
        return []

    header = _find_header(table[0])
    rows: list[ParsedRow] = []
    if header:
        if "name" in header:
            name_cols = header["name"]
        else:
            name_cols = sorted(
                header.get("surname", []) + header.get("first", []) + header.get("middle", [])
            )
        group_col = header["group"][0] if "group" in header else None
        for row in table[1:]:
            name = " ".join(row[i] for i in name_cols if i < len(row) and row[i])
            group = row[group_col] if group_col is not None and group_col < len(row) else ""
            parsed = make_row(name, group)
            if parsed:
                rows.append(parsed)
    else:
        first_column = [row[0] for row in table if row and row[0]]
        if (
            first_column
            and all(cell.isdigit() for cell in first_column)
            and max(len(row) for row in table) >= 2
        ):
            table = [row[1:] for row in table]  # a running number, not a name
        for row in table:
            name, group = _name_and_group(row)
            parsed = make_row(name, group)
            if parsed:
                rows.append(parsed)
    _check_row_limit(rows)
    return rows


def _too_many_rows() -> RosterImportError:
    return RosterImportError(
        _("Too many rows: at most %(max)s students can be imported at a time. Split the list.")
        % {"max": MAX_ROWS}
    )


def _check_row_limit(rows: list) -> None:
    if len(rows) > MAX_ROWS:
        raise _too_many_rows()


# ---- pasted text --------------------------------------------------------------------------


def _split_line(line: str) -> list[str]:
    if "\t" in line:
        return line.split("\t")
    if ";" in line:
        return line.split(";")
    if "," in line:
        return line.split(",")
    return [line]


def clean_keep_tabs(line: str) -> str:
    """Like `clean` but keeps tab characters, which separate the cells of a pasted table."""
    return "\t".join(clean(part) for part in line.split("\t"))


def parse_text(text: str) -> list[ParsedRow]:
    """A pasted list: one student per line.

    A group can follow the name after a semicolon, a comma or a tab. List numbers and bullets
    are dropped. A first line made of header words ("ПІБ; Клас") switches to table reading.
    """
    text = text or ""
    if len(text.encode("utf-8", errors="ignore")) > MAX_BYTES:
        raise RosterImportError(_("The text is too large (limit 2 MB)."))
    lines = [line for line in text.splitlines() if line.strip()]
    if not lines:
        return []
    if _is_header_line(_split_line(lines[0])):
        delimiter = "\t" if "\t" in lines[0] else ";" if ";" in lines[0] else ","
        if delimiter not in lines[0]:
            delimiter = "\t"
        return _table_to_rows([line.split(delimiter) for line in lines])

    rows: list[ParsedRow] = []
    for line in lines:
        cells = _split_line(strip_marker(clean_keep_tabs(line)))
        non_empty = [cell for cell in cells if clean(cell)]
        if len(non_empty) >= 2 and clean(non_empty[0]).isdigit():
            non_empty = non_empty[1:]  # "1<TAB>Name<TAB>Group" from a spreadsheet
        if len(cells) == 2 and len(non_empty) == 1 and not clean(cells[0]):
            name, group = "", non_empty[0]  # ";7-A": a group but nobody in it
        else:
            name, group = _name_and_group(non_empty)
        parsed = make_row(name, group)
        if parsed:
            rows.append(parsed)
        if len(rows) > MAX_ROWS:
            break
    _check_row_limit(rows)
    return rows


# ---- CSV ----------------------------------------------------------------------------------

_ZIP_MAGIC = b"PK\x03\x04"
_OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"  # the old binary .xls


def _decode(data: bytes) -> str:
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):  # Excel "Unicode text"
        return data.decode("utf-16", errors="replace")
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        pass
    try:
        return data.decode("cp1251")
    except UnicodeDecodeError:
        return data.decode("cp1251", errors="replace")


def _detect_delimiter(lines: list[str]) -> str:
    """The delimiter that splits most of the first lines into the same number (>= 2) of cells."""
    best_delimiter, best_score = ",", (0, 0)
    for candidate in ("	", ";", ","):  # on a tie the one that is rarer inside names wins
        try:
            widths = [len(row) for row in csv.reader(lines, delimiter=candidate) if row]
        except csv.Error:
            continue
        if not widths:
            continue
        width, count = Counter(widths).most_common(1)[0]
        if width >= 2 and (count, width) > best_score:
            best_delimiter, best_score = candidate, (count, width)
    return best_delimiter


def parse_csv(data: bytes) -> list[ParsedRow]:
    """CSV (or TSV / text) bytes. UTF-8 (with or without BOM), UTF-16 and Windows-1251."""
    if len(data) > MAX_BYTES:
        raise RosterImportError(_("The file is too large (limit 2 MB)."))
    if data.startswith(_ZIP_MAGIC) or data.startswith(_OLE_MAGIC):
        raise RosterImportError(_("This is not a CSV file. Choose a CSV or XLSX file."))
    text = _decode(data)
    if "\x00" in text:
        raise RosterImportError(_("This does not look like a text or CSV file."))
    lines = [line for line in text.splitlines() if line.strip()]
    if not lines:
        return []
    delimiter = _detect_delimiter(lines[:30])
    try:
        table = []
        for row in csv.reader(io.StringIO(text, newline=""), delimiter=delimiter):
            if any(cell.strip() for cell in row):
                table.append(row)
            if len(table) > MAX_ROWS + 1:  # +1: the header row
                raise _too_many_rows()
    except csv.Error:
        raise RosterImportError(_("The file could not be read as CSV.")) from None
    return _table_to_rows(table)


# ---- XLSX ---------------------------------------------------------------------------------


def _cell_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def parse_xlsx(data: bytes) -> list[ParsedRow]:
    """An Excel workbook: the first sheet with data. Cell values only; formulas are not run."""
    if len(data) > MAX_BYTES:
        raise RosterImportError(_("The file is too large (limit 2 MB)."))
    try:
        import openpyxl
    except ImportError:
        raise RosterImportError(
            _(
                "Reading Excel files needs the optional xlsx component, which is not installed. "
                "Save the sheet as CSV instead, or ask the administrator to install the xlsx "
                "extra."
            )
        ) from None

    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            if sum(info.file_size for info in archive.infolist()) > MAX_XLSX_UNPACKED:
                raise RosterImportError(_("The workbook is too large to read."))
    except zipfile.BadZipFile:
        raise RosterImportError(_("The file could not be read as an Excel workbook.")) from None

    try:
        # read_only streams the sheet; data_only returns the stored values, never the formulas.
        workbook = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except Exception:
        raise RosterImportError(_("The file could not be read as an Excel workbook.")) from None
    try:
        for sheet in workbook.worksheets:
            table = []
            for scanned, values in enumerate(
                sheet.iter_rows(values_only=True, max_col=MAX_COLUMNS), start=1
            ):
                if scanned > MAX_XLSX_SCANNED_ROWS:
                    raise RosterImportError(_("The sheet has too many rows."))
                row = [_cell_text(value) for value in values]
                if any(cell.strip() for cell in row):
                    table.append(row)
                if len(table) > MAX_ROWS + 1:
                    raise _too_many_rows()
            if table:
                return _table_to_rows(table)
    except RosterImportError:
        raise
    except Exception:
        raise RosterImportError(_("The file could not be read as an Excel workbook.")) from None
    finally:
        workbook.close()
    return []


def parse_file(data: bytes) -> list[ParsedRow]:
    """Pick the parser from the content, not from the file name."""
    if data.startswith(_ZIP_MAGIC):
        return parse_xlsx(data)
    if data.startswith(_OLE_MAGIC):
        raise RosterImportError(
            _("Old .xls files are not supported. Save the sheet as .xlsx or CSV.")
        )
    return parse_csv(data)
