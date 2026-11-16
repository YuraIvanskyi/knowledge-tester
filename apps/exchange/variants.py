"""Variants of a test (docs/exchange-format.md, "Variants").

A test holds either ``questions`` (one version for everybody) or ``variants``: a list of
``{"id", "title", "questions"}``, parallel versions of which every taker gets one. Settings,
grading and taker fields are shared. Question ids are unique across the whole test.

Code that works for one attempt never looks at ``variants``: it asks for ``view(test, id)``, which
is the same test with plain ``questions`` (those of that variant). Code that works for a whole
test or session uses the helpers below. Pure functions on the stored dicts.
"""

from __future__ import annotations

import random

from django.utils.translation import gettext as _

MAX_VARIANTS = 10


def variant_list(test: dict) -> list[dict]:
    """The variants of a test; empty for a plain test."""
    variants = test.get("variants")
    return variants if isinstance(variants, list) else []


def has_variants(test: dict) -> bool:
    return bool(variant_list(test))


def variant_ids(test: dict) -> list[str]:
    return [str(v.get("id", "")) for v in variant_list(test)]


def all_questions(test: dict) -> list[dict]:
    """Every question of the test, variant after variant."""
    variants = variant_list(test)
    if not variants:
        return test.get("questions") or []
    return [q for variant in variants for q in variant.get("questions") or []]


def find(test: dict, variant_id: str | None) -> dict | None:
    for variant in variant_list(test):
        if str(variant.get("id", "")) == str(variant_id):
            return variant
    return None


def view(test: dict, variant_id: str | None) -> dict:
    """The test as one taker sees it: plain ``questions``, no ``variants``.

    A plain test is returned as it is. An unknown or empty id gives the first variant, so an
    attempt made before the test got variants (impossible for a published revision, but cheap
    to survive) still has questions."""
    variants = variant_list(test)
    if not variants:
        return test
    chosen = find(test, variant_id) or variants[0]
    flat = {key: value for key, value in test.items() if key != "variants"}
    flat["questions"] = chosen.get("questions") or []
    return flat


def question_count(test: dict) -> int:
    """How many questions a taker gets (of the first variant when there are several)."""
    return len(view(test, None).get("questions") or [])


def label(test: dict, variant_id: str | None) -> str:
    """What people see: the variant's own title, or "Variant 2". Empty for a plain test."""
    for number, variant in enumerate(variant_list(test), start=1):
        if str(variant.get("id", "")) == str(variant_id):
            return str(variant.get("title") or "") or _("Variant %(n)s") % {"n": number}
    return ""


def for_token(test: dict, token) -> str:
    """The variant that belongs to an attempt token: random, but always the same for one token,
    so the page shown before the attempt exists and the attempt itself agree. "" for a plain
    test."""
    ids = variant_ids(test)
    if not ids:
        return ""
    return ids[random.Random(f"variant:{token}").randrange(len(ids))]
