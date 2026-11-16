"""Import and validate a Test Document (plan §11).

`import_document` never raises on bad input: every problem ends up in the `ValidationReport`.
On success `ImportResult.document` is the normalised canonical document: every question and
option has an id, and every default is filled in.
"""

from __future__ import annotations

import difflib
import json
import math
import re
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError

from .document import (
    CHOICE_TYPES,
    COMMON_QUESTION_FIELDS,
    FORMAT_NAME,
    FORMAT_VERSION,
    TYPE_FIELDS,
    Grading,
    Option,
    Question,
    Settings,
    TakerField,
    TestBody,
    TestDocument,
    Threshold,
    Variant,
)
from .report import ValidationReport

OPTION_IDS = "abcdefghijklmnopqrst"
_FENCE = re.compile(r"^\s*```[A-Za-z]*[ \t]*\r?\n(.*?)\r?\n[ \t]*```\s*$", re.DOTALL)


@dataclass
class ImportResult:
    document: dict | None
    report: ValidationReport

    @property
    def ok(self) -> bool:
        return self.document is not None and self.report.ok


def import_document(data: str | bytes | dict) -> ImportResult:
    report = ValidationReport()
    raw = _load(data, report)
    if raw is None:
        return ImportResult(None, report)

    _warn_unknown_fields(raw, report)

    try:
        doc = TestDocument.model_validate(raw)
    except ValidationError as exc:
        for err in exc.errors():
            path, message = _describe_error(err)
            report.error(path, message)
        return ImportResult(None, report)

    if not _check_shape(doc, report):
        return ImportResult(None, report)
    _assign_ids(doc, report)
    _check_semantics(doc, report)
    if not report.ok:
        return ImportResult(None, report)
    return ImportResult(_normalise(doc), report)


# ---------------------------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------------------------


def _load(data: str | bytes | dict, report: ValidationReport) -> dict | None:
    if isinstance(data, dict):
        return data
    if isinstance(data, bytes):
        try:
            data = data.decode("utf-8-sig")
        except UnicodeDecodeError:
            report.error("file", "not valid UTF-8 text. Save the file as plain UTF-8 JSON.")
            return None
    text = data.lstrip("﻿")
    fence = _FENCE.match(text)
    if fence:
        text = fence.group(1)
        report.warn("file", "the Markdown code fence (```) around the JSON was removed.")
    if not text.strip():
        report.error("file", "the file is empty. Paste or upload a Knowledge Tester test (JSON).")
        return None
    try:
        raw = json.loads(text)
    except json.JSONDecodeError as exc:
        line = text.splitlines()[exc.lineno - 1] if exc.lineno <= len(text.splitlines()) else ""
        report.error(
            "file",
            f"not valid JSON at line {exc.lineno}, column {exc.colno}: {exc.msg}. "
            f"Check for a missing comma, quote or bracket near: {line.strip()[:80]!r}.",
        )
        return None
    if not isinstance(raw, dict):
        report.error("file", 'the top level must be an object: { "format": ..., "test": ... }.')
        return None
    return raw


# ---------------------------------------------------------------------------------------------
# Unknown fields (warnings)
# ---------------------------------------------------------------------------------------------


def _hint(key: str, candidates: Any) -> str:
    candidates = sorted(candidates)
    starts = [c for c in candidates if c.startswith(key.lower()) or key.lower().startswith(c)]
    close = starts or difflib.get_close_matches(key, candidates, n=1, cutoff=0.6)
    return f' Did you mean "{close[0]}"?' if close else ""


def _warn_unknown_fields(raw: dict, report: ValidationReport) -> None:
    def flat(obj: Any, model: type, path: str) -> None:
        if not isinstance(obj, dict):
            return
        known = set(model.model_fields)
        for key in obj:
            if key not in known:
                report.warn(
                    f"{path}.{key}" if path else key,
                    "unknown field, ignored." + _hint(str(key), known),
                )

    def each(items: Any, model: type, path: str) -> None:
        if isinstance(items, list):
            for i, item in enumerate(items):
                flat(item, model, f"{path}[{i}]")

    flat(raw, TestDocument, "")
    test = raw.get("test")
    if not isinstance(test, dict):
        return
    flat(test, TestBody, "test")
    flat(test.get("settings"), Settings, "test.settings")
    each(test.get("taker_fields"), TakerField, "test.taker_fields")
    flat(test.get("grading"), Grading, "test.grading")
    if isinstance(test.get("grading"), dict):
        each(test["grading"].get("thresholds"), Threshold, "test.grading.thresholds")

    groups = [("test.questions", test.get("questions"))]
    if isinstance(test.get("variants"), list):
        each(test["variants"], Variant, "test.variants")
        groups += [
            (f"test.variants[{k}].questions", v.get("questions"))
            for k, v in enumerate(test["variants"])
            if isinstance(v, dict)
        ]
    for prefix, questions in groups:
        if isinstance(questions, list):
            _warn_unknown_question_fields(prefix, questions, report, each)


def _warn_unknown_question_fields(prefix: str, questions: list, report, each) -> None:
    for i, q in enumerate(questions):
        if not isinstance(q, dict):
            continue
        path = f"{prefix}[{i}]"
        qtype = q.get("type")
        known = set(Question.model_fields)
        used = (
            COMMON_QUESTION_FIELDS | TYPE_FIELDS[qtype]
            if isinstance(qtype, str) and qtype in TYPE_FIELDS
            else known
        )
        for key in q:
            if key not in known:
                report.warn(f"{path}.{key}", "unknown field, ignored." + _hint(str(key), used))
            elif key == "image":
                report.warn(f"{path}.image", "images are not supported yet, ignored.")
            elif key not in used:
                report.warn(f"{path}.{key}", f"not used by {qtype} questions, ignored.")
        each(q.get("options"), Option, f"{path}.options")


# ---------------------------------------------------------------------------------------------
# Pydantic errors -> plain messages
# ---------------------------------------------------------------------------------------------


def _path(loc: tuple) -> str:
    out = ""
    for part in loc:
        out += f"[{part}]" if isinstance(part, int) else (f".{part}" if out else str(part))
    return out or "file"


def _show(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float):
        return str(value)
    if isinstance(value, str):
        return json.dumps(value[:40] + ("..." if len(value) > 40 else ""), ensure_ascii=False)
    if isinstance(value, list):
        return "a list"
    if isinstance(value, dict):
        return "an object"
    return repr(value)


def _describe_error(err: dict) -> tuple[str, str]:
    kind, loc, value, ctx = err["type"], err["loc"], err.get("input"), err.get("ctx") or {}
    path = _path(loc)
    field = str(loc[-1]) if loc else ""
    got = _show(value)
    if kind == "missing":
        if path == "format":
            return path, f'required. Add "format": "{FORMAT_NAME}" at the top level.'
        if path == "version":
            return path, f'required. Add "version": {FORMAT_VERSION} at the top level.'
        if path == "test":
            return path, 'required. Add a "test" object with "title" and "questions".'
        return path, f'required field "{field}" is missing.'
    if kind == "literal_error":
        expected = ctx.get("expected", "")
        values = re.findall(r"'([^']*)'", expected) or [expected]
        message = (
            ("must be " if len(values) == 1 else "must be one of: ")
            + ", ".join(f'"{v}"' for v in values)
            + f", got {got}."
        )
        if isinstance(value, str) and (close := difflib.get_close_matches(value, values, 1, 0.5)):
            message += f' Did you mean "{close[0]}"?'
        if path == "version":
            message = f"unsupported version {got}. This app reads version {FORMAT_VERSION}."
        return path, message
    if kind in ("string_type",):
        return path, f"must be text, got {got}."
    if kind == "string_too_short":
        n = ctx.get("min_length", 1)
        return path, "must not be empty." if n == 1 else f"must have at least {n} characters."
    if kind == "string_too_long":
        return path, f"must have at most {ctx.get('max_length')} characters, got {len(value)}."
    if kind in ("greater_than_equal", "greater_than"):
        bound = ctx.get("ge", ctx.get("gt"))
        return path, f"must be {bound:g} or more, got {got}."
    if kind in ("less_than_equal", "less_than"):
        bound = ctx.get("le", ctx.get("lt"))
        return path, f"must be {bound:g} or less, got {got}."
    if kind in ("bool_type", "bool_parsing"):
        return path, f"must be true or false (without quotes), got {got}."
    if kind in ("int_type", "int_parsing", "int_from_float"):
        return path, f"must be a whole number, got {got}."
    if kind in ("float_type", "float_parsing"):
        return path, f"must be a number, got {got}."
    if kind == "too_short":
        return (
            path,
            f"must have at least {ctx.get('min_length')} item(s), got {ctx.get('actual_length')}.",
        )
    if kind == "too_long":
        return (
            path,
            f"must have at most {ctx.get('max_length')} item(s), got {ctx.get('actual_length')}.",
        )
    if kind == "list_type":
        return path, f"must be a list [ ... ], got {got}."
    if kind in ("model_type", "dict_type", "model_attributes_type"):
        return path, f"must be an object {{ ... }}, got {got}."
    if kind == "value_error":
        return path, f"{ctx.get('error')}, got {got}."
    return path, f"{err['msg']} (got {got})."


# ---------------------------------------------------------------------------------------------
# Ids and semantic checks
# ---------------------------------------------------------------------------------------------


def _check_shape(doc: TestDocument, report: ValidationReport) -> bool:
    """A test has "questions" or "variants". False stops the import (errors are reported)."""
    test = doc.test
    if test.questions is None and test.variants is None:
        report.error("test.questions", 'required field "questions" is missing.')
        return False
    if test.questions is not None and test.variants is not None:
        report.error(
            "test.variants",
            'a test has either "questions" or "variants", not both. Put every question '
            'into a variant, or remove "variants".',
        )
        return False
    if test.variants is not None and len(test.variants) == 1:
        report.warn(
            "test.variants",
            "only one variant, so the test is imported without variants.",
        )
        test.questions = test.variants[0].questions
        test.variants = None
    return True


def _question_groups(test: TestBody) -> list[tuple[str, list[Question]]]:
    """(path, questions) per list of questions: one for a plain test, one per variant."""
    if test.variants is None:
        return [("test.questions", test.questions or [])]
    return [(f"test.variants[{k}].questions", v.questions) for k, v in enumerate(test.variants)]


def _assign_ids(doc: TestDocument, report: ValidationReport) -> None:
    variants = doc.test.variants or []
    seen_variants: dict[str, int] = {}
    for k, variant in enumerate(variants):
        if variant.id is None:
            continue
        if variant.id in seen_variants:
            report.error(
                f"test.variants[{k}]",
                f'id "{variant.id}" is already used by test.variants[{seen_variants[variant.id]}]. '
                'Variant ids must be unique: change this "id" or remove it to get one generated.',
            )
        seen_variants.setdefault(variant.id, k)
    used_variants = set(seen_variants)
    number = 0
    for variant in variants:
        if variant.id is None:
            number += 1
            while f"v{number}" in used_variants:
                number += 1
            variant.id = f"v{number}"
            used_variants.add(variant.id)

    # Question ids are unique in the whole test, also across variants: an answer is stored
    # under the question id alone.
    groups = _question_groups(doc.test)
    seen: dict[str, str] = {}
    for path, questions in groups:
        for i, q in enumerate(questions):
            if q.id is None:
                continue
            if q.id in seen:
                report.error(
                    f"{path}[{i}]",
                    f'id "{q.id}" is already used by {seen[q.id]}. '
                    'Ids must be unique: change this "id" or remove it to get one generated.',
                )
            seen.setdefault(q.id, f"{path}[{i}]")
    used = set(seen)
    counter = 0
    for _, questions in groups:
        for q in questions:
            if q.id is None:
                counter += 1
                while f"q{counter}" in used:
                    counter += 1
                q.id = f"q{counter}"
                used.add(q.id)

    for path, questions in groups:
        _assign_option_ids(path, questions, report)


def _assign_option_ids(path: str, questions: list[Question], report: ValidationReport) -> None:
    for i, q in enumerate(questions):
        if not q.options:
            continue
        opt_seen: dict[str, int] = {}
        for j, opt in enumerate(q.options):
            if opt.id is not None:
                if opt.id in opt_seen:
                    report.error(
                        f'{path}[{i}] (id "{q.id}", {q.type})',
                        f'option id "{opt.id}" is used more than once (options[{opt_seen[opt.id]}] '
                        f"and options[{j}]). Option ids must be unique within a question.",
                    )
                opt_seen.setdefault(opt.id, j)
        used_opts = set(opt_seen)
        letters = (c for c in OPTION_IDS if c not in used_opts)
        for opt in q.options:
            if opt.id is None:
                opt.id = next(letters, None) or f"o{len(used_opts) + 1}"
                used_opts.add(opt.id)


def _parse_number(text: str) -> float | None:
    try:
        value = float(text.strip().replace(" ", "").replace(",", "."))
    except ValueError:
        return None
    return value if math.isfinite(value) else None


def _check_semantics(doc: TestDocument, report: ValidationReport) -> None:
    test = doc.test
    groups = _question_groups(test)
    for path, questions in groups:
        for i, q in enumerate(questions):
            _check_question(q, f'{path}[{i}] (id "{q.id}", {q.type})', report)

    keys: set[str] = set()
    for i, field in enumerate(test.taker_fields):
        if field.key in keys:
            report.error(
                f"test.taker_fields[{i}]",
                f'key "{field.key}" is used more than once. Taker field keys must be unique.',
            )
        keys.add(field.key)

    _check_grading(test.grading, report)
    everything = [q for _, questions in groups for q in questions]
    if test.grading.enabled and all(q.points == 0 for q in everything):
        report.warn("test.questions", "every question has 0 points, so nothing will be graded.")
    if test.variants:
        totals = [_num(sum(q.points for q in v.questions)) for v in test.variants]
        if len(set(totals)) > 1:
            listed = ", ".join(f"{v.id}: {t}" for v, t in zip(test.variants, totals, strict=True))
            report.warn(
                "test.variants",
                f"the variants are worth different numbers of points ({listed}). Grades are "
                "based on percent, so this works, but equal totals are easier to explain.",
            )


def _check_question(q: Question, where: str, report: ValidationReport) -> None:
    if q.type in CHOICE_TYPES:
        _check_choice(q, where, report)
    elif q.type == "short_answer":
        _check_short_answer(q, where, report)


def _check_choice(q: Question, where: str, report: ValidationReport) -> None:
    options = q.options or []
    if not 2 <= len(options) <= 20:
        report.error(
            where,
            f'needs 2 to 20 options, found {len(options)}. Add an "options" list such as '
            '[{"text": "Yes", "correct": true}, {"text": "No"}].',
        )
        return
    correct = [o for o in options if o.correct]
    if q.type == "single_choice" and len(correct) != 1:
        if not correct:
            report.error(
                where,
                'no option is marked correct. Add "correct": true to exactly one option.',
            )
        else:
            report.error(
                where,
                f"{len(correct)} options are marked correct, but a single_choice question needs "
                'exactly one. Keep "correct": true on one option, or change the type to '
                '"multiple_choice".',
            )
    elif q.type == "multiple_choice":
        if not correct:
            report.error(
                where,
                'no option is marked correct. Add "correct": true to at least one option.',
            )
        elif (q.scoring or "partial") == "partial" and len(correct) == len(options):
            report.warn(where, "every option is marked correct, so partial scoring cannot work.")
        if q.scoring == "per_option":
            missing = [o.id for o in options if o.weight is None]
            if missing:
                report.error(
                    where,
                    'scoring is "per_option" but these options have no "weight": '
                    + ", ".join(f'"{m}"' for m in missing)
                    + '. Add a numeric "weight" to every option.',
                )
    elif q.type == "choose_n":
        if q.n is None:
            report.error(
                where,
                f'"n" is missing. Set "n" to the number of correct options ({len(correct)}).',
            )
        elif len(correct) != q.n:
            report.error(
                where,
                f'"n" is {q.n} but {len(correct)} option(s) are marked correct. '
                f'Mark exactly {q.n} options as correct, or change "n".',
            )


def _check_short_answer(q: Question, where: str, report: ValidationReport) -> None:
    accept = q.accept or []
    if not accept:
        report.error(
            where,
            'no accepted answers. Add "accept": ["..."] with at least one accepted answer.',
        )
        return
    if any(not a.strip() for a in accept):
        report.error(where, '"accept" contains an empty answer. Remove it or write the answer.')
    if (q.mode or "text") == "numeric":
        for a in accept:
            if a.strip() and _parse_number(a) is None:
                report.error(
                    where,
                    f'mode is "numeric" but accepted answer {json.dumps(a, ensure_ascii=False)} '
                    'is not a number. Use numbers such as "0.75", or set "mode": "text".',
                )


def _check_grading(grading: Grading, report: ValidationReport) -> None:
    path = "test.grading"
    if grading.scale != "custom":
        if grading.thresholds:
            report.warn(
                f"{path}.thresholds",
                'only used with "scale": "custom", ignored.',
            )
        return
    thresholds = grading.thresholds or []
    if not thresholds:
        report.error(
            f"{path}.thresholds",
            'scale is "custom" but no thresholds are given. Add for example '
            '[{"min_percent": 90, "label": "A"}, {"min_percent": 0, "label": "F"}].',
        )
        return
    percents = [t.min_percent for t in thresholds]
    if any(a <= b for a, b in zip(percents, percents[1:], strict=False)):
        report.error(
            f"{path}.thresholds",
            'must be sorted from the highest "min_percent" to the lowest, with no repeated values.',
        )
    labels = [t.label for t in thresholds]
    if len(set(labels)) != len(labels):
        report.error(f"{path}.thresholds", 'every "label" must be different.')
    if min(percents) > 0:
        report.warn(
            f"{path}.thresholds",
            'no threshold has "min_percent": 0, so low results get no grade. '
            "Add a last entry with min_percent 0.",
        )


# ---------------------------------------------------------------------------------------------
# Normalised output
# ---------------------------------------------------------------------------------------------


def _num(value: float) -> int | float:
    return int(value) if float(value).is_integer() else value


def _normalise_option(o: Option) -> dict:
    out: dict[str, Any] = {"id": o.id, "text": o.text, "correct": o.correct}
    if o.weight is not None:
        out["weight"] = _num(o.weight)
    return out


def _normalise_question(q: Question) -> dict:
    out: dict[str, Any] = {
        "id": q.id,
        "type": q.type,
        "text": q.text,
        "points": _num(q.points),
        "required": q.required,
    }
    if q.hint:
        out["hint"] = q.hint
    options = [_normalise_option(o) for o in q.options or []]
    if q.type == "single_choice":
        out["penalty"] = _num(q.penalty or 0)
        out["options"] = options
    elif q.type == "multiple_choice":
        out["scoring"] = q.scoring or "partial"
        out["options"] = options
    elif q.type == "choose_n":
        out["n"] = q.n
        out["options"] = options
    elif q.type == "short_answer":
        out["mode"] = q.mode or "text"
        out["accept"] = [a.strip() for a in q.accept or []]
        out["case_sensitive"] = bool(q.case_sensitive)
        out["tolerance"] = _num(q.tolerance or 0)
        out["review_unmatched"] = bool(q.review_unmatched)
    elif q.rubric:
        out["rubric"] = q.rubric
    return out


def _normalise(doc: TestDocument) -> dict:
    t = doc.test
    grading: dict[str, Any] = {
        "enabled": t.grading.enabled,
        "scale": t.grading.scale,
        "pass_percent": _num(t.grading.pass_percent),
    }
    if t.grading.scale == "custom":
        grading["thresholds"] = [
            {"min_percent": _num(x.min_percent), "label": x.label}
            for x in t.grading.thresholds or []
        ]
    test: dict[str, Any] = {
        "title": t.title,
        "description": t.description,
        "language": t.language,
        "settings": t.settings.model_dump(),
        "taker_fields": [f.model_dump() for f in t.taker_fields],
        "grading": grading,
    }
    if t.variants:
        test["variants"] = [
            {
                "id": v.id,
                "title": v.title,
                "questions": [_normalise_question(q) for q in v.questions],
            }
            for v in t.variants
        ]
    else:
        test["questions"] = [_normalise_question(q) for q in t.questions or []]
    return {"format": FORMAT_NAME, "version": FORMAT_VERSION, "test": test}
