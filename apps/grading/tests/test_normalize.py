from decimal import Decimal

import pytest

from apps.grading.normalize import normalize_text, parse_number


@pytest.mark.parametrize(
    ("raw", "kwargs", "expected"),
    [
        ("  Kyiv  ", {}, "kyiv"),
        ("New \t  York\n", {}, "new york"),
        ("Kyiv.", {}, "kyiv"),
        ("Kyiv?!...", {}, "kyiv"),
        ("Kyiv …", {}, "kyiv"),
        ("Kyiv", {"case_sensitive": True}, "Kyiv"),
        ("KYIV", {"case_sensitive": True}, "KYIV"),
        # NFKC: full-width and ligature forms
        ("Ｋｙｉｖ", {}, "kyiv"),
        ("ﬁsh", {}, "fish"),
        # Ukrainian apostrophe variants all unify
        ("м'ята", {}, "м'ята"),
        ("м’ята", {}, "м'ята"),
        ("мʼята", {}, "м'ята"),
        ("м`ята", {}, "м'ята"),
        ("м‘ята", {}, "м'ята"),
        ("М’ЯТА", {}, "м'ята"),
        # dashes and quotes
        ("a–b", {}, "a-b"),
        ("a—b", {}, "a-b"),
        ("a−b", {}, "a-b"),
        ("“quoted”", {}, '"quoted"'),
        ("«цитата»", {}, '"цитата"'),
        # look-alike mapping is opt-in
        ("kиїв", {}, "kиїв"),
        ("kиїв", {"lookalike": True}, "київ"),
        ("Lviv", {"lookalike": True}, "lvіv"),
        ("", {}, ""),
        (None, {}, ""),
    ],
)
def test_normalize_text(raw, kwargs, expected):
    assert normalize_text(raw, **kwargs) == expected


def test_lookalike_makes_mixed_script_equal():
    latin_slip = normalize_text("мoва", lookalike=True)  # Latin o inside a Cyrillic word
    assert latin_slip == normalize_text("мова", lookalike=True)
    assert normalize_text("мoва") != normalize_text("мова")


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("0.75", Decimal("0.75")),
        ("0,75", Decimal("0.75")),
        (" 0,75 ", Decimal("0.75")),
        ("-1,5", Decimal("-1.5")),
        ("−1.5", Decimal("-1.5")),
        ("+2", Decimal("2")),
        ("42", Decimal("42")),
        (".5", Decimal("0.5")),
        ("5.", Decimal("5")),
        ("1 000,5", Decimal("1000.5")),
        ("1 000,5", Decimal("1000.5")),
        ("1,234.5", Decimal("1234.5")),
        ("1.234,5", Decimal("1234.5")),
        (3, Decimal(3)),
        (0.75, Decimal("0.75")),
        (Decimal("2.5"), Decimal("2.5")),
        ("", None),
        ("  ", None),
        ("abc", None),
        ("1,2,3", None),
        ("1.2.3", None),
        ("1e3", None),
        ("NaN", None),
        ("Infinity", None),
        ("1/2", None),
        (None, None),
        (True, None),
    ],
)
def test_parse_number(raw, expected):
    assert parse_number(raw) == expected


@pytest.mark.parametrize("variant", ["м´ята", "м’ята", "мʼята", "м`ята", "м′ята", "м'ята"])
def test_every_apostrophe_variant_matches_the_plain_one(variant):
    """The acute accent U+00B4 used to be split by NFKC before it reached the apostrophe table."""
    assert normalize_text(variant) == normalize_text("м'ята")
