"""Text and number normalisation for short answers (plan §9.3). Pure Python."""

from __future__ import annotations

import re
import unicodedata
from decimal import Decimal, InvalidOperation

# Apostrophe variants -> "'" (matters for Ukrainian words such as "м'ята")
_APOSTROPHES = dict.fromkeys("’ʼ‘ʹ′´`ʻ՚＇", "'")
_DASHES = dict.fromkeys("‐‑‒–—―−⁃", "-")
_QUOTES = dict.fromkeys("“”„‟«»″〝〞", '"')
_APOSTROPHE_TABLE = str.maketrans(_APOSTROPHES)
_DASH_TABLE = str.maketrans(_DASHES)
_UNIFY = str.maketrans({**_APOSTROPHES, **_DASHES, **_QUOTES})

# Latin letters that look like Cyrillic ones (keyboard-layout slips). Lowercase and uppercase.
_LOOKALIKE_PAIRS = {
    "a": "а",
    "c": "с",
    "e": "е",
    "i": "і",
    "o": "о",
    "p": "р",
    "x": "х",
    "y": "у",
    "k": "к",
    "h": "н",
    "t": "т",
    "m": "м",
    "b": "в",
}
_LOOKALIKE = str.maketrans(
    {**_LOOKALIKE_PAIRS, **{k.upper(): v.upper() for k, v in _LOOKALIKE_PAIRS.items()}}
)

_TRAILING_PUNCT = ".,;:!?… "
_WS = re.compile(r"\s+")


def normalize_text(value: object, *, case_sensitive: bool = False, lookalike: bool = False) -> str:
    """Normalise a short answer for comparison. Order follows plan §9.3."""
    if value is None:
        return ""
    # Apostrophes first: NFKC would turn the acute accent U+00B4 into "space + combining accent".
    text = unicodedata.normalize("NFKC", str(value).translate(_APOSTROPHE_TABLE))  # 1. NFKC
    text = _WS.sub(" ", text).strip()  # 2. trim + collapse whitespace
    if not case_sensitive:  # 3. casefold
        text = text.casefold()
    text = text.translate(_UNIFY)  # 4+5. apostrophes, dashes, quotes
    text = text.rstrip(_TRAILING_PUNCT)  # 6. trailing punctuation
    if lookalike:
        text = text.translate(_LOOKALIKE)
    return text


def parse_number(value: object) -> Decimal | None:
    """Parse a number typed by a person. Accepts "," and "." as the decimal separator.

    Spaces (also non-breaking) are ignored as thousands separators. If both separators occur,
    the last one is the decimal separator. Returns None if the text is not a single number.
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int | Decimal):
        return Decimal(value) if Decimal(value).is_finite() else None
    if isinstance(value, float):
        return Decimal(str(value)) if value == value and abs(value) != float("inf") else None
    text = unicodedata.normalize("NFKC", str(value)).translate(_DASH_TABLE)
    text = re.sub(r"\s+", "", text)
    if not text:
        return None
    has_comma, has_dot = "," in text, "." in text
    if has_comma and has_dot:
        decimal_sep = "," if text.rfind(",") > text.rfind(".") else "."
        thousands = "." if decimal_sep == "," else ","
        if text.count(decimal_sep) != 1:
            return None
        text = text.replace(thousands, "")
    elif has_comma or has_dot:
        sep = "," if has_comma else "."
        if text.count(sep) != 1:
            return None
    text = text.replace(",", ".")
    if not re.fullmatch(r"[+-]?(\d+\.?\d*|\.\d+)", text):
        return None
    try:
        return Decimal(text)
    except InvalidOperation:
        return None
