"""Offline / CSP guard for the student pages after the UX review (UX-01, 03, 05, 10, 15): the test
page with and without the "unanswered" panel, the cancelled-attempt pages, the class session
form, and the taker scripts."""

import re
from pathlib import Path

import pytest
from django.test import Client

from apps.delivery import services
from apps.delivery.tests.conftest import make_revision, make_student
from apps.people.models import Group
from tests.test_offline import csp_violations, external_urls

pytestmark = pytest.mark.django_db

STATIC = Path(__file__).resolve().parent.parent / "static"


def pages(teacher):
    revision = make_revision(teacher)
    group = Group.objects.create(owner=teacher, name="7-A")
    ann = make_student(teacher, group, "Ann Lee", pin="5829")
    free = services.create_sitting(revision=revision, user=teacher, title="free")
    klass = services.create_sitting(
        revision=revision, user=teacher, title="class", group=group, use_pin=True
    )
    out = []

    browser = Client()
    out.append(browser.get(f"/s/{free.code}/"))  # the test page as landing page
    browser.post(f"/s/{free.code}/", {"tf_name": "Ann Lee"})
    out.append(browser.get(f"/s/{free.code}/take/"))
    out.append(
        browser.post(f"/s/{free.code}/submit/", {"form_sent": "1", "q_q2": ["a"]})
    )  # missing
    out.append(  # the "unanswered" panel
        browser.post(f"/s/{free.code}/submit/", {"form_sent": "1", "q_q1": "a", "q_q2": ["a"]})
    )
    services.void_attempt(free.attempts.get())
    out.append(browser.get(f"/s/{free.code}/done/"))  # cancelled, retry link
    out.append(browser.get(f"/s/{free.code}/"))  # cancelled note on the fresh test page

    pupil = Client()
    out.append(pupil.get(f"/s/{klass.code}/"))
    out.append(pupil.post(f"/s/{klass.code}/", {"student": ann.pk, "pin": "0000"}))
    out.append(Client().post("/s/enter/", {"code": "NOPE00"}))
    return out


def test_taker_pages_have_no_external_urls_or_inline_code(teacher):
    responses = pages(teacher)
    assert len(responses) == 9
    for response in responses:
        assert response.status_code == 200, response.request["PATH_INFO"]
        html = response.content.decode()
        assert external_urls(html) == [], response.request["PATH_INFO"]
        assert csp_violations(html) == [], response.request["PATH_INFO"]
    assert 'id="unanswered"' in responses[3].content.decode()
    assert 'id="save-status"' in responses[1].content.decode()


def test_taker_scripts_and_styles_stay_small_and_self_contained():
    for name in ("js/autosave.js", "js/timer.js", "js/namepicker.js", "css/delivery.css"):
        text = (STATIC / name).read_text(encoding="utf-8")
        assert not re.search(r"https?://|@import|//cdn", text), name
    scripts = sum(
        (STATIC / f"js/{n}.js").stat().st_size for n in ("autosave", "timer", "namepicker")
    )
    assert scripts < 25 * 1024  # plan budget is 25 KB gzipped; source size is a safe upper bound
