"""Page-level CSP / offline check for the results pages: no inline style, script or handlers."""

import re

import pytest
from django.urls import reverse

from .test_views import attempts, login, other_teacher, sitting, teacher  # noqa: F401

pytestmark = pytest.mark.django_db

INLINE_SCRIPT = re.compile(r"<script(?![^>]*\bsrc=)", re.I)
HANDLER = re.compile(r"\son[a-z]+\s*=", re.I)
EXTERNAL = re.compile(r"(?:src|href)=[\"']https?://", re.I)


def _urls(the_sitting, the_attempts):
    return [
        reverse("reports:session", args=[the_sitting.pk]),
        reverse("reports:session", args=[the_sitting.pk]) + "?status=voided&sort=-score",
        reverse("reports:attempt", args=[the_attempts[0].pk]),
        reverse("reports:attempt_void", args=[the_attempts[0].pk]),
    ]


def test_results_pages_have_no_inline_code_or_external_assets(login, sitting, attempts):  # noqa: F811
    for url in _urls(sitting, attempts):
        html = login.get(url).content.decode()
        assert 'style="' not in html, url
        assert "<style" not in html, url
        assert not INLINE_SCRIPT.search(html), url
        assert not HANDLER.search(html), url
        assert not EXTERNAL.search(html), url


def test_rejected_review_page_has_no_inline_code(login, attempts):  # noqa: F811
    html = login.post(
        reverse("reports:attempt", args=[attempts[0].pk]), {"points_q3": "99"}
    ).content.decode()
    assert 'style="' not in html and not HANDLER.search(html)
    assert 'aria-invalid="true"' in html


def test_print_stylesheet_hides_the_review_controls():
    from pathlib import Path

    css = (Path(__file__).resolve().parents[3] / "static/css/print.css").read_text("utf-8")
    assert ".no-print" in css and "button" in css and "form" in css
