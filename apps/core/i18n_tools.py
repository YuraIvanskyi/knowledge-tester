"""Translation catalog tooling that does not need GNU gettext (xgettext / msgfmt).

* ``extract``  collects msgids from templates and Python files into the ``django.po`` catalog
* ``compile_catalog`` turns ``django.po`` into ``django.mo`` (committed, so users need no tools)
* ``merge``    fills ``django.po`` from translation fragments (``*.po`` files in a directory)
* ``check``    lists untranslated / fuzzy entries and placeholder mismatches

``scripts/i18n.py`` is the command line front end. Tests can import ``untranslated()`` /
``check()``.

Known limitation: a literal ``%`` inside ``{% translate "..." %}`` is stored by Django's template
tooling as ``%%``; avoid literal percent signs in translated template strings.
"""

from __future__ import annotations

import ast
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import polib

BASE_DIR = Path(__file__).resolve().parent.parent.parent
LOCALE_DIR = BASE_DIR / "locale"
DEFAULT_LANG = "uk"

PLURAL_FORMS = {
    "uk": (
        "nplurals=3; plural=(n%10==1 && n%100!=11 ? 0 : "
        "n%10>=2 && n%10<=4 && (n%100<10 || n%100>=20) ? 1 : 2);"
    ),
}
NPLURALS = {"uk": 3}

# Python directories scanned for translatable calls, and file names that are skipped.
PY_ROOTS = ("apps", "config")
SKIP_DIRS = {"tests", "migrations", "__pycache__"}
SKIP_FILES = {"conftest.py", "i18n_tools.py"}

# function name -> (index of msgid, index of plural msgid or None, index of context or None)
_CALLS = {
    "gettext": (0, None, None),
    "gettext_lazy": (0, None, None),
    "gettext_noop": (0, None, None),
    "_": (0, None, None),
    "ngettext": (0, 1, None),
    "ngettext_lazy": (0, 1, None),
    "pgettext": (1, None, 0),
    "pgettext_lazy": (1, None, 0),
    "npgettext": (1, 2, 0),
    "npgettext_lazy": (1, 2, 0),
}

Key = tuple[str | None, str]  # (msgctxt, msgid)


def po_path(lang: str = DEFAULT_LANG) -> Path:
    return LOCALE_DIR / lang / "LC_MESSAGES" / "django.po"


def mo_path(lang: str = DEFAULT_LANG) -> Path:
    return po_path(lang).with_suffix(".mo")


@dataclass
class Found:
    msgid: str
    plural: str | None = None
    context: str | None = None
    refs: list[tuple[str, int]] = field(default_factory=list)


# --------------------------------------------------------------------------- extraction


def _const_str(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _call_name(func: ast.AST) -> str | None:
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def _record_call(
    node: ast.Call, lineno: int, ref_path: str, found: dict[Key, Found], warnings: list[str]
) -> None:
    name = _call_name(node.func)
    if name not in _CALLS:
        return
    if name == "_" and isinstance(node.func, ast.Attribute):
        return
    id_i, plural_i, ctx_i = _CALLS[name]
    if len(node.args) <= max(i for i in (id_i, plural_i, ctx_i) if i is not None):
        return
    msgid = _const_str(node.args[id_i])
    plural = _const_str(node.args[plural_i]) if plural_i is not None else None
    context = _const_str(node.args[ctx_i]) if ctx_i is not None else None
    if msgid is None or (plural_i is not None and plural is None):
        warnings.append(f"{ref_path}:{lineno}: non-literal argument to {name}(), skipped")
        return
    if ctx_i is not None and context is None:
        warnings.append(f"{ref_path}:{lineno}: non-literal context in {name}(), skipped")
        return
    if not msgid:
        return
    item = found.setdefault((context, msgid), Found(msgid, plural, context))
    if plural and not item.plural:
        item.plural = plural
    item.refs.append((ref_path, lineno))


def _scan_source(source: str, ref_path: str, found: dict[Key, Found], warnings: list[str]) -> None:
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Call):
            _record_call(node, node.lineno, ref_path, found, warnings)


# Start of a translation call inside templatize() output, which is not valid Python as a whole
# (non-translatable template text is blanked with letters).
_TEMPLATE_CALL = re.compile(r"(?<![\w.])(?:np|p|n)?gettext(?:_lazy|_noop)?\(|(?<![\w.])_\(")


def _scan_template_source(
    source: str, ref_path: str, found: dict[Key, Found], warnings: list[str]
) -> None:
    for match in _TEMPLATE_CALL.finditer(source):
        lineno = source.count("\n", 0, match.start()) + 1
        end = match.end()
        while True:
            end = source.find(")", end)
            if end == -1:
                warnings.append(f"{ref_path}:{lineno}: could not parse translation call")
                break
            end += 1
            try:
                tree = ast.parse(source[match.start() : end].strip(), mode="eval")
            except SyntaxError:
                continue
            _record_call(tree.body, lineno, ref_path, found, warnings)
            break


def _rel(path: Path) -> str:
    return path.relative_to(BASE_DIR).as_posix()


def _python_files() -> list[Path]:
    files: list[Path] = []
    for root in PY_ROOTS:
        for path in sorted((BASE_DIR / root).rglob("*.py")):
            rel_parts = path.relative_to(BASE_DIR).parts
            if (
                SKIP_DIRS & set(rel_parts)
                or path.name in SKIP_FILES
                or path.name.startswith("test_")
            ):
                continue
            files.append(path)
    return files


def collect_messages() -> tuple[dict[Key, Found], list[str]]:
    """Return ({(context, msgid): Found}, warnings) for every wrapped string in the project."""
    from django.utils.translation.template import templatize

    found: dict[Key, Found] = {}
    warnings: list[str] = []
    for path in sorted((BASE_DIR / "templates").rglob("*.html")):
        rel = _rel(path)
        text = path.read_text(encoding="utf-8")
        _scan_template_source(templatize(text), rel, found, warnings)
    for path in _python_files():
        rel = _rel(path)
        try:
            _scan_source(path.read_text(encoding="utf-8"), rel, found, warnings)
        except SyntaxError as exc:
            warnings.append(f"{rel}: could not parse ({exc})")
    return found, warnings


def _new_catalog(lang: str) -> polib.POFile:
    po = polib.POFile(wrapwidth=100)
    po.metadata = {
        "Project-Id-Version": "knowledge-tester",
        "Language": lang,
        "MIME-Version": "1.0",
        "Content-Type": "text/plain; charset=UTF-8",
        "Content-Transfer-Encoding": "8bit",
        "Plural-Forms": PLURAL_FORMS.get(lang, "nplurals=2; plural=(n != 1);"),
    }
    po.metadata_is_fuzzy = False
    return po


def _forms(lang: str) -> int:
    return NPLURALS.get(lang, 2)


def extract(lang: str = DEFAULT_LANG) -> dict:
    """Create or update the catalog; keeps existing translations. Returns a stats dict."""
    found, warnings = collect_messages()
    path = po_path(lang)
    old = polib.pofile(str(path), wrapwidth=100) if path.exists() else None
    old_by_key: dict[Key, polib.POEntry] = {}
    if old is not None:
        old_by_key = {(e.msgctxt, e.msgid): e for e in old}

    po = _new_catalog(lang)
    if old is not None:
        po.metadata.update({k: v for k, v in old.metadata.items() if k not in po.metadata})
        po.metadata["Language"] = lang
        po.metadata["Plural-Forms"] = PLURAL_FORMS.get(lang, po.metadata["Plural-Forms"])
        if old.header:
            po.header = old.header

    added = 0
    ordered = sorted(found.values(), key=lambda f: (f.refs[0][0], f.refs[0][1]))
    for item in ordered:
        prev = old_by_key.pop((item.context, item.msgid), None)
        entry = polib.POEntry(
            msgid=item.msgid,
            msgid_plural=item.plural or "",
            msgctxt=item.context,
            occurrences=sorted(set(item.refs)),
        )
        if prev is not None and not prev.obsolete:
            entry.flags = list(prev.flags)
            entry.comment = prev.comment
            entry.tcomment = prev.tcomment
            if item.plural:
                entry.msgstr_plural = {
                    i: (prev.msgstr_plural.get(i, "") if prev.msgid_plural else "")
                    for i in range(_forms(lang))
                }
                if not prev.msgid_plural and prev.msgstr:
                    entry.msgstr_plural[0] = prev.msgstr
            else:
                entry.msgstr = prev.msgstr or (
                    prev.msgstr_plural.get(0, "") if prev.msgid_plural else ""
                )
        else:
            if prev is not None and prev.obsolete:
                entry.msgstr = prev.msgstr
                entry.msgstr_plural = dict(prev.msgstr_plural)
            added += 1
            if item.plural and not entry.msgstr_plural:
                entry.msgstr_plural = {i: "" for i in range(_forms(lang))}
        po.append(entry)

    obsolete = 0
    for prev in old_by_key.values():
        if not (prev.msgstr or any(prev.msgstr_plural.values())):
            continue  # untranslated and gone: just drop it
        prev.obsolete = True
        prev.occurrences = []
        po.append(prev)
        obsolete += 1

    path.parent.mkdir(parents=True, exist_ok=True)
    po.save(str(path))
    return {
        "total": len(ordered),
        "added": added,
        "obsolete": obsolete,
        "warnings": warnings,
        "path": path,
    }


# --------------------------------------------------------------------------- compile


def compile_catalog(lang: str = DEFAULT_LANG) -> tuple[Path, int]:
    """Write django.mo next to django.po; returns (path, number of translated entries)."""
    po = polib.pofile(str(po_path(lang)))
    out = mo_path(lang)
    po.save_as_mofile(str(out))
    return out, len(po.translated_entries())


# --------------------------------------------------------------------------- merge


def _has_translation(entry: polib.POEntry) -> bool:
    if entry.msgid_plural:
        return bool(entry.msgstr_plural) and all(entry.msgstr_plural.values())
    return bool(entry.msgstr)


def _same_translation(a: polib.POEntry, b: polib.POEntry) -> bool:
    return a.msgstr == b.msgstr and a.msgstr_plural == b.msgstr_plural


def merge(fragments_dir: Path, lang: str = DEFAULT_LANG, overwrite: bool = False) -> dict:
    """Fill django.po from every ``*.po`` in ``fragments_dir`` (matching msgid + msgctxt)."""
    path = po_path(lang)
    po = polib.pofile(str(path), wrapwidth=100)
    by_key = {(e.msgctxt, e.msgid): e for e in po if not e.obsolete}
    unmatched: list[str] = []
    conflicts: list[str] = []
    filled = 0
    seen: dict[Key, tuple[str, polib.POEntry]] = {}

    for frag_path in sorted(Path(fragments_dir).glob("*.po")):
        frag = polib.pofile(str(frag_path))
        for fe in frag:
            if fe.obsolete or not _has_translation(fe):
                continue
            key = (fe.msgctxt, fe.msgid)
            label = f"{frag_path.name}: {fe.msgid!r}" + (
                f" [ctx {fe.msgctxt!r}]" if fe.msgctxt else ""
            )
            if key in seen and not _same_translation(seen[key][1], fe):
                conflicts.append(f"{label} differs from {seen[key][0]} (first one kept)")
                continue
            seen.setdefault(key, (frag_path.name, fe))
            target = by_key.get(key)
            if target is None:
                unmatched.append(label)
                continue
            if bool(target.msgid_plural) != bool(fe.msgid_plural):
                unmatched.append(f"{label} (plural/singular mismatch with the catalog)")
                continue
            if _has_translation(target) and not overwrite:
                if not _same_translation(target, fe):
                    conflicts.append(f"{label} already translated differently (use --overwrite)")
                continue
            if target.msgid_plural:
                target.msgstr_plural = {i: fe.msgstr_plural.get(i, "") for i in range(_forms(lang))}
            else:
                target.msgstr = fe.msgstr
            if "fuzzy" in target.flags:
                target.flags.remove("fuzzy")
            if "fuzzy" in fe.flags:
                target.flags.append("fuzzy")
            filled += 1

    po.save(str(path))
    return {
        "filled": filled,
        "unmatched": unmatched,
        "conflicts": conflicts,
        "untranslated": untranslated(lang),
    }


# --------------------------------------------------------------------------- check

_PLACEHOLDER = re.compile(r"%(?:\([^)]+\))?[#0\- +]*\d*(?:\.\d+)?[sdifrxXeEgGc]")


def _placeholders(text: str) -> Counter:
    return Counter(_PLACEHOLDER.findall(text.replace("%%", "")))


def untranslated(lang: str = DEFAULT_LANG) -> list[str]:
    """msgids (non-obsolete) that are untranslated, partly translated or fuzzy."""
    po = polib.pofile(str(po_path(lang)))
    result = []
    for entry in po:
        if entry.obsolete:
            continue
        if "fuzzy" in entry.flags or not _has_translation(entry):
            result.append(entry.msgid)
    return result


def placeholder_errors(lang: str = DEFAULT_LANG) -> list[str]:
    """Translations whose %(name)s / %s placeholders differ from the msgid."""
    po = polib.pofile(str(po_path(lang)))
    errors = []
    for entry in po:
        if entry.obsolete or not _has_translation(entry):
            continue
        if entry.msgid_plural:
            expected = _placeholders(entry.msgid_plural)
            for index, text in sorted(entry.msgstr_plural.items()):
                got = _placeholders(text)
                # The form used for n == 1 may spell the number out instead of using it.
                ok = got == expected or (index == 0 and not got - expected)
                if not ok:
                    errors.append(
                        f"{entry.msgid!r} msgstr[{index}]: placeholders {dict(got)} "
                        f"!= {dict(expected)}"
                    )
            if len(entry.msgstr_plural) != _forms(lang):
                errors.append(f"{entry.msgid!r}: expected {_forms(lang)} plural forms")
        else:
            expected, got = _placeholders(entry.msgid), _placeholders(entry.msgstr)
            if got != expected:
                errors.append(f"{entry.msgid!r}: placeholders {dict(got)} != {dict(expected)}")
    return errors


def check(lang: str = DEFAULT_LANG) -> list[str]:
    """Human readable problems; an empty list means the catalog is complete and consistent."""
    problems = [f"untranslated or fuzzy: {m!r}" for m in untranslated(lang)]
    problems += [f"placeholder mismatch: {e}" for e in placeholder_errors(lang)]
    return problems
