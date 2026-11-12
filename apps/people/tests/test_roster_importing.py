"""Parsers for pasted lists, CSV and XLSX (pure functions, no database)."""

import io
import sys

import pytest

from apps.people import importing
from apps.people.importing import (
    ISSUE_BAD_GROUP,
    ISSUE_EMPTY,
    ISSUE_GROUP_TOO_LONG,
    ISSUE_NO_LETTERS,
    ISSUE_TOO_LONG,
    RosterImportError,
    parse_csv,
    parse_file,
    parse_text,
    parse_xlsx,
)


def pairs(rows):
    return [(r.full_name, r.group_name) for r in rows]


# ---- pasted text -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Іваненко Петро\nКоваль Олена", [("Іваненко Петро", ""), ("Коваль Олена", "")]),
        # numbering and bullets
        (
            "1. Іваненко Петро\n2) Коваль Олена\n(3) Мельник Іра\n4 - Шевченко Софія",
            [
                ("Іваненко Петро", ""),
                ("Коваль Олена", ""),
                ("Мельник Іра", ""),
                ("Шевченко Софія", ""),
            ],
        ),
        (
            "- Іваненко Петро\n* Коваль Олена\n• Мельник Іра\n–  Шевченко Софія",
            [
                ("Іваненко Петро", ""),
                ("Коваль Олена", ""),
                ("Мельник Іра", ""),
                ("Шевченко Софія", ""),
            ],
        ),
        ("12.Іваненко Петро", [("Іваненко Петро", "")]),
        # groups after ; , or tab
        ("Іваненко Петро; 7-А", [("Іваненко Петро", "7-А")]),
        ("Іваненко Петро, 7-А", [("Іваненко Петро", "7-А")]),
        ("Іваненко Петро\t7-А", [("Іваненко Петро", "7-А")]),
        ("Іваненко Петро; Alpha", [("Іваненко Петро", "Alpha")]),
        ("Іваненко Петро, Іванович, 7-А", [("Іваненко Петро Іванович", "7-А")]),
        # surname, first name in one cell stays one person
        ("Іваненко, Петро", [("Іваненко Петро", "")]),
        ("Іваненко; Петро", [("Іваненко Петро", "")]),
        ("Іваненко, Петро, Іванович", [("Іваненко Петро Іванович", "")]),
        # spreadsheet paste with a running number
        (
            "1\tІваненко Петро\t7-А\n2\tКоваль Олена\t7-Б",
            [("Іваненко Петро", "7-А"), ("Коваль Олена", "7-Б")],
        ),
        # Ukrainian names with apostrophes and hyphens are kept as typed
        (
            "Коваль Дем’ян\nМ'ясоїд Іван\nАнна-Марія Ковальчук\nО'Брайен Пат",
            [
                ("Коваль Дем’ян", ""),
                ("М'ясоїд Іван", ""),
                ("Анна-Марія Ковальчук", ""),
                ("О'Брайен Пат", ""),
            ],
        ),
        # odd whitespace and invisible characters
        ("  Іваненко   Петро ​\n\n\t\n   \r\n", [("Іваненко Петро", "")]),
        ('"Іваненко Петро"', [("Іваненко Петро", "")]),
        # Windows line endings, trailing separators
        ("Іваненко Петро;\r\nКоваль Олена;\r\n", [("Іваненко Петро", ""), ("Коваль Олена", "")]),
        ("", []),
        ("   \n \n", []),
    ],
)
def test_parse_text(text, expected):
    rows = parse_text(text)
    assert pairs(rows) == expected
    assert all(not r.issues for r in rows)


def test_parse_text_flags_odd_rows_instead_of_dropping_them():
    rows = parse_text("12345\n;7-А\n***; ??\nІваненко Петро; ***\n" + "Я" * 201)
    assert [r.issues for r in rows] == [
        [ISSUE_NO_LETTERS],
        [ISSUE_EMPTY],
        [ISSUE_EMPTY, ISSUE_BAD_GROUP],  # "***" is read as a bullet, so no name is left
        [ISSUE_BAD_GROUP],
        [ISSUE_TOO_LONG],
    ]


def test_group_name_too_long_is_flagged():
    rows = parse_text("Іваненко Петро; 7-" + "А" * 201)
    assert rows[0].issues == [ISSUE_GROUP_TOO_LONG]


def test_parse_text_does_not_run_or_trust_formula_like_input():
    rows = parse_text('=HYPERLINK("http://x","y") Петро')
    assert len(rows) == 1  # kept as plain text; exports escape it, nothing evaluates it


def test_header_line_in_pasted_table():
    rows = parse_text("ПІБ\tКлас\nІваненко Петро\t7-А\nКоваль Олена\t7-Б")
    assert pairs(rows) == [("Іваненко Петро", "7-А"), ("Коваль Олена", "7-Б")]
    rows = parse_text("Name; Group\nIvan Petrenko; 7-A")
    assert pairs(rows) == [("Ivan Petrenko", "7-A")]


def test_single_header_word_is_skipped():
    assert pairs(parse_text("Name\nIvan Petrenko")) == [("Ivan Petrenko", "")]


def test_a_name_that_looks_like_a_header_word_in_the_middle_is_kept():
    assert pairs(parse_text("Ivan Petrenko\nName")) == [("Ivan Petrenko", ""), ("Name", "")]


def test_parse_text_row_limit():
    ok = "\n".join(f"Student {i}" for i in range(importing.MAX_ROWS))
    assert len(parse_text(ok)) == importing.MAX_ROWS
    with pytest.raises(RosterImportError, match="Too many rows"):
        parse_text(ok + "\nOne more")


def test_parse_text_size_limit():
    with pytest.raises(RosterImportError, match="too large"):
        parse_text("я" * (importing.MAX_BYTES // 2 + 10))


# ---- CSV -------------------------------------------------------------------------------------


def csv_bytes(text, encoding="utf-8-sig"):
    return text.encode(encoding)


@pytest.mark.parametrize(
    "data",
    [
        csv_bytes("Прізвище;Ім'я;Клас\nІваненко;Петро;7-А\nКоваль;Олена;7-Б\n"),
        csv_bytes("Прізвище;Ім'я;Клас\nІваненко;Петро;7-А\nКоваль;Олена;7-Б\n", "utf-8"),
        csv_bytes("Прізвище;Ім'я;Клас\r\nІваненко;Петро;7-А\r\nКоваль;Олена;7-Б\r\n", "cp1251"),
        csv_bytes("Прізвище,Ім’я,Клас\nІваненко,Петро,7-А\nКоваль,Олена,7-Б\n"),
        csv_bytes("Прізвище\tІм'я\tКлас\nІваненко\tПетро\t7-А\nКоваль\tОлена\t7-Б\n"),
        csv_bytes("Surname,First name,Class\nІваненко,Петро,7-А\nКоваль,Олена,7-Б\n"),
        csv_bytes("Прізвище;Ім'я;Клас\nІваненко;Петро;7-А\nКоваль;Олена;7-Б\n", "utf-16"),
        csv_bytes('"Прізвище";"Ім\'я";"Клас"\n"Іваненко";"Петро";"7-А"\n"Коваль";"Олена";"7-Б"\n'),
    ],
)
def test_parse_csv_surname_and_first_name_columns_are_joined(data):
    assert pairs(parse_csv(data)) == [("Іваненко Петро", "7-А"), ("Коваль Олена", "7-Б")]


def test_parse_csv_full_name_column_and_patronymic():
    data = csv_bytes("№;ПІБ;Клас;Телефон\n1;Іваненко Петро Іванович;7-А;123\n2;Коваль Олена;;456\n")
    assert pairs(parse_csv(data)) == [("Іваненко Петро Іванович", "7-А"), ("Коваль Олена", "")]
    data = csv_bytes("Прізвище;Ім'я;По батькові\nІваненко;Петро;Іванович\n")
    assert pairs(parse_csv(data)) == [("Іваненко Петро Іванович", "")]


def test_parse_csv_without_header():
    assert pairs(parse_csv(csv_bytes("Іваненко Петро\nКоваль Олена\n"))) == [
        ("Іваненко Петро", ""),
        ("Коваль Олена", ""),
    ]
    assert pairs(parse_csv(csv_bytes("Іваненко Петро;7-А\nКоваль Олена;7-Б\n"))) == [
        ("Іваненко Петро", "7-А"),
        ("Коваль Олена", "7-Б"),
    ]
    # a running number in the first column is not a name
    assert pairs(parse_csv(csv_bytes("1;Іваненко Петро;7-А\n2;Коваль Олена;7-Б\n"))) == [
        ("Іваненко Петро", "7-А"),
        ("Коваль Олена", "7-Б"),
    ]
    # surname, first name without a header
    assert pairs(parse_csv(csv_bytes("Іваненко;Петро\nКоваль;Олена\n"))) == [
        ("Іваненко Петро", ""),
        ("Коваль Олена", ""),
    ]


def test_parse_csv_quoted_field_with_the_delimiter_inside():
    data = csv_bytes('Name,Group\n"Іваненко, Петро",7-А\n')
    assert pairs(parse_csv(data)) == [("Іваненко, Петро", "7-А")]


def test_parse_csv_skips_blank_lines_and_keeps_odd_rows_as_invalid():
    rows = parse_csv(csv_bytes("Name,Group\n\n,\nIvan Petrenko,7-A\n,7-B\n"))
    assert [(r.full_name, r.issues) for r in rows] == [
        ("Ivan Petrenko", []),
        ("", [ISSUE_EMPTY]),
    ]


def test_parse_csv_errors():
    assert parse_csv(b"") == []
    with pytest.raises(RosterImportError, match="too large"):
        parse_csv(b"a" * (importing.MAX_BYTES + 1))
    with pytest.raises(RosterImportError):
        parse_csv(b"Name\x00Group\x00\x01\x02")
    with pytest.raises(RosterImportError, match="not a CSV"):
        parse_csv(b"PK\x03\x04rest")


def test_parse_csv_row_limit():
    body = "Name\n" + "\n".join(f"Student {i}" for i in range(importing.MAX_ROWS + 1))
    with pytest.raises(RosterImportError, match="Too many rows"):
        parse_csv(csv_bytes(body))


def test_parse_csv_garbage_bytes_do_not_crash():
    rows = parse_csv(bytes(range(1, 128)) * 3)  # no NUL, not a sensible list
    assert isinstance(rows, list)
    rows = parse_csv("Іван Петренко".encode("cp1251") + b"\x98\x98")  # undefined cp1251 byte
    assert len(rows) == 1


# ---- XLSX ------------------------------------------------------------------------------------

openpyxl = pytest.importorskip("openpyxl")


def workbook_bytes(sheets):
    """sheets: list of (title, rows). Returns the .xlsx file as bytes."""
    book = openpyxl.Workbook()
    book.remove(book.active)
    for title, rows in sheets:
        sheet = book.create_sheet(title)
        for row in rows:
            sheet.append(row)
    buffer = io.BytesIO()
    book.save(buffer)
    return buffer.getvalue()


def test_parse_xlsx_with_header_and_numeric_group():
    data = workbook_bytes(
        [
            (
                "Клас",
                [
                    ["Прізвище", "Ім'я", "Клас", "Примітка"],
                    ["Іваненко", "Петро", "7-А", None],
                    ["Коваль", "Дем'ян", 8, "x"],
                    [None, None, None, None],
                    ["Мельник", "Олена", 8.0, None],
                ],
            )
        ]
    )
    assert pairs(parse_xlsx(data)) == [
        ("Іваненко Петро", "7-А"),
        ("Коваль Дем'ян", "8"),
        ("Мельник Олена", "8"),
    ]


def test_parse_xlsx_uses_first_sheet_with_data_and_headerless_lists():
    data = workbook_bytes(
        [("Empty", []), ("List", [["Іваненко Петро"], ["Коваль Олена"]]), ("Other", [["Не цей"]])]
    )
    assert pairs(parse_xlsx(data)) == [("Іваненко Петро", ""), ("Коваль Олена", "")]
    assert parse_xlsx(workbook_bytes([("Empty", [])])) == []


def test_parse_xlsx_never_evaluates_formulas():
    data = workbook_bytes(
        [("S", [["Name", "Group"], ["=1+1", "7-А"], ['=CONCATENATE("Іван"," Петренко")', "7-А"]])]
    )
    rows = parse_xlsx(data)
    # openpyxl stores no cached result for formulas written by it: nothing to read, nothing run
    assert all("=" not in r.full_name for r in rows)
    assert [r.issues for r in rows] == [[ISSUE_EMPTY], [ISSUE_EMPTY]]


@pytest.mark.parametrize(
    "data",
    [b"not a zip at all", b"PK\x03\x04broken", b"PK\x05\x06" + b"\x00" * 18],
)
def test_parse_xlsx_rejects_non_workbooks(data):
    with pytest.raises(RosterImportError, match="could not be read"):
        parse_xlsx(data)


def test_parse_xlsx_rejects_a_zip_that_is_not_a_workbook():
    import zipfile

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("hello.txt", "hi")
    with pytest.raises(RosterImportError, match="could not be read"):
        parse_xlsx(buffer.getvalue())


def test_parse_xlsx_refuses_a_zip_bomb(monkeypatch):
    monkeypatch.setattr(importing, "MAX_XLSX_UNPACKED", 10)
    with pytest.raises(RosterImportError, match="too large"):
        parse_xlsx(workbook_bytes([("S", [["Name"], ["Іван Петренко"]])]))


def test_parse_xlsx_row_limit():
    rows = [["Name"], *[[f"Student {i}"] for i in range(importing.MAX_ROWS + 1)]]
    with pytest.raises(RosterImportError, match="Too many rows"):
        parse_xlsx(workbook_bytes([("S", rows)]))


def test_parse_xlsx_without_the_extra_installed(monkeypatch):
    monkeypatch.setitem(sys.modules, "openpyxl", None)  # makes `import openpyxl` fail
    with pytest.raises(RosterImportError, match="xlsx"):
        parse_xlsx(b"PK\x03\x04")


def test_parse_file_picks_the_parser_from_the_content_not_the_name():
    xlsx = workbook_bytes([("S", [["Name"], ["Іван Петренко"]])])
    assert pairs(parse_file(xlsx)) == [("Іван Петренко", "")]
    assert pairs(parse_file("Name\nІван Петренко\n".encode())) == [("Іван Петренко", "")]
    with pytest.raises(RosterImportError, match="xls"):
        parse_file(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 20)


# ---- helpers ---------------------------------------------------------------------------------


def test_parsed_row_roundtrip_survives_junk():
    row = importing.ParsedRow("Іван Петренко", "7-А", [ISSUE_EMPTY])
    assert importing.ParsedRow.from_dict(row.to_dict()) == row
    junk = importing.ParsedRow.from_dict({"n": None, "g": 5, "i": [1, "empty"]})
    assert (junk.full_name, junk.group_name, junk.issues) == ("", "5", ["empty"])


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("  a​b \t c\n", "ab c"),
        ("й", "й"),  # decomposed breve is composed
        (None, ""),
        (12, "12"),
    ],
)
def test_clean(value, expected):
    assert importing.clean(value) == expected
