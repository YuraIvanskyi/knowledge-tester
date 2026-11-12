"""Name normalisation shared by the roster, the taker name picker and attempt linking.

Pure Python. `normalize_name` is what `Student.name_key` stores, so changing it means
re-saving every student.
"""

from __future__ import annotations

import re
import unicodedata

# Every apostrophe-like character becomes a plain one (Ukrainian names: Дем'ян, Дем’ян, Демʼян).
_APOSTROPHES = "\u2019\u02bc\u02b9\u2018`\u00b4\u2032"
_APOSTROPHE_TABLE = {ord(ch): "'" for ch in _APOSTROPHES}
_JUNK = re.compile(r"[^\w' -]+", re.UNICODE)  # keeps letters, digits, apostrophe, hyphen, space


def normalize_name(value: str) -> str:
    """Case-folded, single-spaced, apostrophe- and dash-unified form of a person's name."""
    text = unicodedata.normalize("NFKC", value or "").translate(_APOSTROPHE_TABLE)
    text = text.replace("\u2010", "-").replace("\u2011", "-").replace("\u2013", "-")
    text = _JUNK.sub(" ", text)
    return " ".join(text.casefold().split())


def name_tokens(value: str) -> list[str]:
    """Normalised words of a name, in the order given (surname/first-name order varies)."""
    return normalize_name(value).split()


def same_person_key(value: str) -> str:
    """Order-independent key: 'Іваненко Петро' and 'Петро Іваненко' give the same key."""
    return " ".join(sorted(name_tokens(value)))
