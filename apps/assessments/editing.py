"""Editing a draft Test Document from browser forms (plan §21.4, KT-202/203/204).

Everything here works on plain dicts and form data, with no request and no database, so it is easy
to test. A draft may be incomplete as a whole (a new test has no questions yet), but every single
question and the settings are validated by the importer before they are stored, so what the editor
writes is always acceptable to `import_document`.
"""

from __future__ import annotations

import copy
import math
import re
from typing import Any

from django.utils.translation import gettext as _

from apps.exchange import variants as test_variants
from apps.exchange.document import CHOICE_TYPES, FORMAT_NAME, FORMAT_VERSION
from apps.exchange.importer import import_document

QUESTION_TYPES = ("single_choice", "multiple_choice", "choose_n", "short_answer", "open")
MIN_OPTION_ROWS = 4
GRADE_SCALES = ("percent", "points", "pass_fail", "ua_12", "five_point")
SHOW_RESULTS = ("none", "score", "full")
SCORING_MODES = ("partial", "all_or_nothing", "per_option")
ANSWER_MODES = ("text", "numeric")


# ---------------------------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------------------------


def blank_document(title: str, language: str) -> dict:
    """A new test with no questions yet (it cannot be published until one is added)."""
    return {
        "format": FORMAT_NAME,
        "version": FORMAT_VERSION,
        "test": {"title": title, "description": "", "language": language, "questions": []},
    }


def questions_of(document: dict, variant_id: str | None = None) -> list[dict]:
    """The editable list of questions: the test's own, or those of one variant (the first
    when `variant_id` names none)."""
    test = document.setdefault("test", {})
    variants = test_variants.variant_list(test)
    if not variants:
        return test.setdefault("questions", [])
    chosen = test_variants.find(test, variant_id) or variants[0]
    return chosen.setdefault("questions", [])


def locate(document: dict, question_id: str) -> tuple[list[dict], int, dict] | None:
    """(the list that holds it, its index there, the question), searching every variant."""
    test = document.setdefault("test", {})
    variants = test_variants.variant_list(test)
    lists = [v.setdefault("questions", []) for v in variants] or [questions_of(document)]
    for questions in lists:
        for index, question in enumerate(questions):
            if question.get("id") == question_id:
                return questions, index, question
    return None


def find_question(document: dict, question_id: str) -> tuple[int, dict] | None:
    found = locate(document, question_id)
    return None if found is None else (found[1], found[2])


def variant_of(document: dict, question_id: str) -> str:
    """Id of the variant that holds the question; "" for a test without variants."""
    for variant in test_variants.variant_list(document.get("test") or {}):
        if any(q.get("id") == question_id for q in variant.get("questions") or []):
            return str(variant.get("id", ""))
    return ""


def next_question_id(document: dict) -> str:
    used = {q.get("id") for q in test_variants.all_questions(document.get("test") or {})}
    number = len(used) + 1
    while f"q{number}" in used:
        number += 1
    return f"q{number}"


def parse_number(text: str) -> float | None:
    """'1,5' and '1.5' both work; blank or junk gives None."""
    try:
        value = float(str(text).strip().replace(" ", "").replace(",", "."))
    except ValueError:
        return None
    return value if math.isfinite(value) else None


def _num(value: float) -> int | float:
    return int(value) if float(value).is_integer() else value


def _issue_texts(result) -> list[str]:
    return [issue.message for issue in result.report.errors]


# ---------------------------------------------------------------------------------------------
# Question form <-> question dict
# ---------------------------------------------------------------------------------------------


def blank_form(question_type: str) -> dict:
    form: dict[str, Any] = {
        "text": "",
        "points": "1",
        "required": False,
        "hint": "",
        "options": [],
    }
    if question_type == "single_choice":
        form["penalty"] = ""
    elif question_type == "multiple_choice":
        form["scoring"] = "partial"
    elif question_type == "choose_n":
        form["n"] = "2"
    elif question_type == "short_answer":
        form.update(
            mode="text",
            accept_text="",
            case_sensitive=False,
            tolerance="",
            review_unmatched=False,
        )
    elif question_type == "open":
        form["rubric"] = ""
    if question_type in CHOICE_TYPES:
        pad_options(form, MIN_OPTION_ROWS)
    return form


def form_from_question(question: dict) -> dict:
    """Fill the form with a stored question's values."""
    form = blank_form(question["type"])
    form["text"] = question.get("text", "")
    form["points"] = str(question.get("points", 1))
    form["required"] = bool(question.get("required"))
    form["hint"] = question.get("hint", "")
    qtype = question["type"]
    if qtype == "single_choice":
        penalty = question.get("penalty") or 0
        form["penalty"] = str(penalty) if penalty else ""
    elif qtype == "multiple_choice":
        form["scoring"] = question.get("scoring", "partial")
    elif qtype == "choose_n":
        form["n"] = str(question.get("n") or 2)
    elif qtype == "short_answer":
        tolerance = question.get("tolerance") or 0
        form.update(
            mode=question.get("mode", "text"),
            accept_text="\n".join(question.get("accept", [])),
            case_sensitive=bool(question.get("case_sensitive")),
            tolerance=str(tolerance) if tolerance else "",
            review_unmatched=bool(question.get("review_unmatched")),
        )
    elif qtype == "open":
        form["rubric"] = question.get("rubric", "")
    if qtype in CHOICE_TYPES:
        form["options"] = [
            {
                "id": o.get("id", ""),
                "text": o.get("text", ""),
                "correct": bool(o.get("correct")),
                "weight": "" if o.get("weight") is None else str(o["weight"]),
            }
            for o in question.get("options", [])
        ]
        pad_options(form, len(form["options"]) + 1)
    return form


def form_from_post(post, question_type: str) -> dict:
    """Read the submitted form back, keeping blank option rows so the page can redisplay them."""
    form = blank_form(question_type)
    form["options"] = []
    form["text"] = post.get("text", "").strip()
    form["points"] = post.get("points", "").strip()
    form["required"] = "required" in post
    form["hint"] = post.get("hint", "").strip()
    if question_type == "single_choice":
        form["penalty"] = post.get("penalty", "").strip()
    elif question_type == "multiple_choice":
        form["scoring"] = post.get("scoring", "partial")
    elif question_type == "choose_n":
        form["n"] = post.get("n", "").strip()
    elif question_type == "short_answer":
        form.update(
            mode=post.get("mode", "text"),
            accept_text=post.get("accept", ""),
            case_sensitive="case_sensitive" in post,
            tolerance=post.get("tolerance", "").strip(),
            review_unmatched="review_unmatched" in post,
        )
    elif question_type == "open":
        form["rubric"] = post.get("rubric", "").strip()
    if question_type in CHOICE_TYPES:
        texts = post.getlist("opt_text")
        ids = post.getlist("opt_id")
        weights = post.getlist("opt_weight")
        correct = set(post.getlist("opt_correct"))
        if question_type == "single_choice":
            correct = set(list(post.getlist("opt_correct"))[:1])
        for index, text in enumerate(texts):
            form["options"].append(
                {
                    "id": ids[index] if index < len(ids) else "",
                    "text": text.strip(),
                    "correct": str(index) in correct,
                    "weight": weights[index].strip() if index < len(weights) else "",
                }
            )
    return form


def pad_options(form: dict, minimum: int) -> None:
    while len(form["options"]) < minimum:
        form["options"].append({"id": "", "text": "", "correct": False, "weight": ""})


def build_question(
    form: dict, question_type: str, question_id: str
) -> tuple[dict | None, list[str]]:
    """Turn form values into a normalised question. Returns (question, error messages)."""
    errors: list[str] = []
    question: dict[str, Any] = {"id": question_id, "type": question_type, "text": form["text"]}

    points = parse_number(form["points"])
    if points is None:
        errors.append(_("Points must be a number, for example 1 or 1.5."))
    else:
        question["points"] = points
    question["required"] = bool(form["required"])
    if form["hint"]:
        question["hint"] = form["hint"]

    if question_type in CHOICE_TYPES:
        options = []
        for row in form["options"]:
            if not row["text"]:
                continue
            option: dict[str, Any] = {"text": row["text"], "correct": bool(row["correct"])}
            if row["id"]:
                option["id"] = row["id"]
            if row["weight"]:
                weight = parse_number(row["weight"])
                if weight is not None:
                    option["weight"] = weight
            options.append(option)
        question["options"] = options
        if question_type == "single_choice" and form["penalty"]:
            penalty = parse_number(form["penalty"])
            if penalty is None:
                errors.append(_("The penalty must be a number between 0 and 1."))
            else:
                question["penalty"] = penalty
        elif question_type == "multiple_choice":
            question["scoring"] = form["scoring"] if form["scoring"] in SCORING_MODES else "partial"
        elif question_type == "choose_n":
            number = parse_number(form["n"])
            if number is None or number != int(number):
                errors.append(_("The number of answers to choose must be a whole number."))
            else:
                question["n"] = int(number)
    elif question_type == "short_answer":
        question["mode"] = form["mode"] if form["mode"] in ANSWER_MODES else "text"
        question["accept"] = [line.strip() for line in form["accept_text"].splitlines()]
        question["accept"] = [line for line in question["accept"] if line]
        question["case_sensitive"] = bool(form["case_sensitive"])
        question["review_unmatched"] = bool(form["review_unmatched"])
        if form["tolerance"]:
            tolerance = parse_number(form["tolerance"])
            if tolerance is None:
                errors.append(_("The tolerance must be a number."))
            else:
                question["tolerance"] = tolerance
    elif question_type == "open" and form["rubric"]:
        question["rubric"] = form["rubric"]

    if errors:
        return None, errors

    wrapped = {
        "format": FORMAT_NAME,
        "version": FORMAT_VERSION,
        "test": {"title": "x", "questions": [question]},
    }
    result = import_document(wrapped)
    if not result.ok:
        return None, _issue_texts(result)
    return result.document["test"]["questions"][0], []


# ---------------------------------------------------------------------------------------------
# Question operations
# ---------------------------------------------------------------------------------------------


def add_question(document: dict, question: dict, variant_id: str | None = None) -> None:
    questions_of(document, variant_id).append(question)


def replace_question(document: dict, question_id: str, question: dict) -> bool:
    found = locate(document, question_id)
    if found is None:
        return False
    found[0][found[1]] = question
    return True


def delete_question(document: dict, question_id: str) -> bool:
    found = locate(document, question_id)
    if found is None:
        return False
    del found[0][found[1]]
    return True


def move_question(document: dict, question_id: str, direction: str) -> bool:
    """Up or down within its own list (a question never moves to another variant)."""
    found = locate(document, question_id)
    if found is None or direction not in ("up", "down"):
        return False
    questions, index = found[0], found[1]
    target = index - 1 if direction == "up" else index + 1
    if not 0 <= target < len(questions):
        return False
    questions[index], questions[target] = questions[target], questions[index]
    return True


def duplicate_question(document: dict, question_id: str) -> str | None:
    """Insert a copy right after the original. Returns the new id."""
    found = locate(document, question_id)
    if found is None:
        return None
    questions, index, original = found
    copy_ = copy.deepcopy(original)
    copy_["id"] = next_question_id(document)
    questions.insert(index + 1, copy_)
    return copy_["id"]


# ---------------------------------------------------------------------------------------------
# Variants
# ---------------------------------------------------------------------------------------------


def add_variant(document: dict, source_id: str | None = None) -> str | None:
    """Add a variant as a copy of an existing one (the last, unless `source_id` names another),
    to be edited afterwards. A test without variants becomes one with two: its questions are
    variant 1. Returns the new variant's id, or None when there is nothing to copy or the
    limit is reached."""
    test = document.setdefault("test", {})
    variants = test_variants.variant_list(test)
    if len(variants) >= test_variants.MAX_VARIANTS:
        return None
    if not variants:
        if not test.get("questions"):
            return None
        variants = [{"id": "v1", "title": "", "questions": test.pop("questions")}]
        test["variants"] = variants
    source = test_variants.find(test, source_id) or variants[-1]
    used = set(test_variants.variant_ids(test))
    number = len(variants) + 1
    while f"v{number}" in used:
        number += 1
    new = {"id": f"v{number}", "title": "", "questions": []}
    variants.append(new)
    for question in source.get("questions") or []:
        copy_ = copy.deepcopy(question)
        copy_["id"] = next_question_id(document)
        new["questions"].append(copy_)
    return new["id"]


def delete_variant(document: dict, variant_id: str) -> bool:
    """Remove a variant with its questions. When one variant is left, the test goes back to
    plain questions."""
    test = document.setdefault("test", {})
    variants = test_variants.variant_list(test)
    target = test_variants.find(test, variant_id)
    if target is None:
        return False
    variants.remove(target)
    if len(variants) <= 1:
        test["questions"] = variants[0].get("questions", []) if variants else []
        del test["variants"]
    return True


# ---------------------------------------------------------------------------------------------
# Test settings
# ---------------------------------------------------------------------------------------------

DEFAULT_SETTINGS = {
    "time_limit_minutes": None,
    "shuffle_questions": False,
    "shuffle_options": False,
    "one_question_per_page": False,
    "show_result": "score",
    "max_attempts": 1,
}
DEFAULT_TAKER_FIELDS = [{"key": "name", "label": "Full name", "required": True}]
TAKER_FIELD_ROWS = 2  # blank rows offered below the existing ones


def settings_form(test: dict) -> dict:
    """Current values of the test settings as form values."""
    settings = {**DEFAULT_SETTINGS, **test.get("settings", {})}
    grading = {"enabled": True, "scale": "percent", "pass_percent": 50, **test.get("grading", {})}
    fields = test.get("taker_fields", DEFAULT_TAKER_FIELDS)
    limit = settings["time_limit_minutes"]
    return {
        "title": test.get("title", ""),
        "description": test.get("description", ""),
        "language": test.get("language", "en"),
        "time_limit_minutes": "" if limit is None else str(limit),
        "shuffle_questions": bool(settings["shuffle_questions"]),
        "shuffle_options": bool(settings["shuffle_options"]),
        "one_question_per_page": bool(settings["one_question_per_page"]),
        "show_result": settings["show_result"],
        "max_attempts": str(settings["max_attempts"]),
        "grading_enabled": bool(grading["enabled"]),
        "scale": grading["scale"],
        "pass_percent": str(grading["pass_percent"]),
        "taker_fields": [
            {"key": f["key"], "label": f["label"], "required": bool(f.get("required"))}
            for f in fields
        ]
        + [{"key": "", "label": "", "required": False} for _i in range(TAKER_FIELD_ROWS)],
    }


def settings_form_from_post(post) -> dict:
    labels = post.getlist("tf_label")
    keys = post.getlist("tf_key")
    required = set(post.getlist("tf_required"))
    return {
        "title": post.get("title", "").strip(),
        "description": post.get("description", "").strip(),
        "language": post.get("language", "").strip(),
        "time_limit_minutes": post.get("time_limit_minutes", "").strip(),
        "shuffle_questions": "shuffle_questions" in post,
        "shuffle_options": "shuffle_options" in post,
        "one_question_per_page": "one_question_per_page" in post,
        "show_result": post.get("show_result", "score"),
        "max_attempts": post.get("max_attempts", "").strip(),
        "grading_enabled": "grading_enabled" in post,
        "scale": post.get("scale", "percent"),
        "pass_percent": post.get("pass_percent", "").strip(),
        "taker_fields": [
            {
                "key": keys[i] if i < len(keys) else "",
                "label": label.strip(),
                "required": str(i) in required,
            }
            for i, label in enumerate(labels)
        ],
    }


def _field_key(label: str, used: set[str]) -> str:
    base = re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_")[:30] or "field"
    key, number = base, 2
    while key in used:
        key = f"{base}_{number}"
        number += 1
    return key


def apply_settings(test: dict, form: dict) -> tuple[dict | None, list[str]]:
    """Validate the settings form and return the updated `test` dict (questions untouched)."""
    errors: list[str] = []

    limit = None
    if form["time_limit_minutes"]:
        number = parse_number(form["time_limit_minutes"])
        if number is None or number != int(number) or number < 1:
            errors.append(_("The time limit must be a whole number of minutes, or empty."))
        else:
            limit = int(number)
    attempts = parse_number(form["max_attempts"])
    if attempts is None or attempts != int(attempts) or attempts < 1:
        errors.append(_("The number of attempts must be a whole number, at least 1."))
        attempts = 1
    pass_percent = parse_number(form["pass_percent"])
    if pass_percent is None or not 0 <= pass_percent <= 100:
        errors.append(_("The pass mark must be a percentage between 0 and 100."))
        pass_percent = 50

    used: set[str] = set()
    taker_fields = []
    for row in form["taker_fields"]:
        if not row["label"]:
            continue
        key = row["key"] or _field_key(row["label"], used)
        used.add(key)
        taker_fields.append({"key": key, "label": row["label"], "required": bool(row["required"])})

    scale = form["scale"]
    current_scale = test.get("grading", {}).get("scale")
    allowed = (*GRADE_SCALES, "custom") if current_scale == "custom" else GRADE_SCALES
    if scale not in allowed:
        scale = "percent"
    grading: dict[str, Any] = {
        "enabled": bool(form["grading_enabled"]),
        "scale": scale,
        "pass_percent": _num(pass_percent),
    }
    if scale == "custom":
        grading["thresholds"] = test.get("grading", {}).get("thresholds", [])

    updated = {
        **test,
        "title": form["title"],
        "description": form["description"],
        "language": form["language"] or test.get("language", "en"),
        "settings": {
            "time_limit_minutes": limit,
            "shuffle_questions": bool(form["shuffle_questions"]),
            "shuffle_options": bool(form["shuffle_options"]),
            "one_question_per_page": bool(form["one_question_per_page"]),
            "show_result": form["show_result"] if form["show_result"] in SHOW_RESULTS else "score",
            "max_attempts": int(attempts),
        },
        "taker_fields": taker_fields,
        "grading": grading,
    }
    if errors:
        return None, errors

    # Reuse the importer's checks on the settings, using one throwaway question.
    probe = {
        "format": FORMAT_NAME,
        "version": FORMAT_VERSION,
        "test": {
            **{k: v for k, v in updated.items() if k not in ("questions", "variants")},
            "questions": [{"type": "open", "text": "x"}],
        },
    }
    result = import_document(probe)
    if not result.ok:
        return None, _issue_texts(result)
    return updated, []
