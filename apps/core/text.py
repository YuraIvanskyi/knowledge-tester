"""Small text helpers shared by several apps (one definition each, so a fix lands everywhere)."""

# Ukrainian alphabet order. Plain code-point order puts ґ є і ї after я, and SQLite sorts the
# same way. ё ъ ы э are included so names of Russian origin sort among the letters too.
_ALPHABET = "абвгґдеєёжзиіїйклмнопрстуфхцчшщъыьэюя"
_LETTER_ORDER = {ch: index for index, ch in enumerate(_ALPHABET)}


def uk_sort_key(text: str) -> tuple:
    """Case-insensitive sort key following the Ukrainian alphabet; other characters sort after
    the letters. Callers that want names compared by words should normalise the text first."""
    return tuple(
        (0, _LETTER_ORDER[ch]) if ch in _LETTER_ORDER else (1, ord(ch)) for ch in text.casefold()
    )


def csv_safe(value: object) -> str:
    """Neutralise spreadsheet formula injection: a leading = + - @ tab or CR gets a quote.

    Every CSV a teacher can download goes through this for text that a student typed."""
    text = "" if value is None else str(value)
    return "'" + text if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text
