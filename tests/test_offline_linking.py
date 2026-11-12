"""Offline / CSP guard for the class-session pages (KT-603, KT-604): the create form, the taker
pages of a class session (with and without a PIN) and the linking page."""

from pathlib import Path

import pytest
from django.test import Client
from django.urls import reverse

from apps.core import lan
from apps.delivery import services
from apps.delivery.tests.conftest import make_revision, make_student
from apps.people.models import Group
from tests.test_offline import csp_violations, external_urls

pytestmark = pytest.mark.django_db

STATIC = Path(__file__).resolve().parent.parent / "static"


@pytest.fixture
def world(teacher):
    revision = make_revision(teacher)
    group = Group.objects.create(owner=teacher, name="7-A")
    students = [
        make_student(teacher, group, f"Student {i:02d}", pin=str(1000 + i) if i % 3 else "")
        for i in range(12)
    ]
    plain = services.create_sitting(revision=revision, user=teacher, title="plain")
    open_class = services.create_sitting(revision=revision, user=teacher, title="c", group=group)
    pin_class = services.create_sitting(
        revision=revision, user=teacher, title="p", group=group, use_pin=True
    )
    # one finished attempt per kind of session so the linking page has rows
    taker = Client()
    taker.post(f"/s/{open_class.code}/", {"student": students[1].pk})
    free = Client()
    free.post(f"/s/{plain.code}/", {"tf_name": "Studnet 02"})
    return {
        "revision": revision,
        "plain": plain,
        "class": open_class,
        "pin": pin_class,
        "students": students,
    }


def pages(client_for, teacher, world):
    anon = Client()
    out = [
        anon.get(f"/s/{world['class'].code}/"),
        anon.get(f"/s/{world['pin'].code}/"),
        # the Start form with errors (nobody picked, wrong PIN)
        anon.post(f"/s/{world['class'].code}/", {"student": ""}),
        anon.post(f"/s/{world['pin'].code}/", {"student": world["students"][1].pk, "pin": "x"}),
        anon.get(f"/s/{world['plain'].code}/"),
    ]
    closed = services.create_sitting(
        revision=world["revision"], user=teacher, title="done", group=world["class"].group
    )
    services.close_sitting(closed)
    out.append(anon.get(f"/s/{closed.code}/"))
    teacher_client = client_for(teacher)
    out.append(teacher_client.get(reverse("delivery:create", args=[world["revision"].pk])))
    for key in ("plain", "class", "pin"):
        out.append(teacher_client.get(reverse("delivery:share", args=[world[key].pk])))
        out.append(teacher_client.get(reverse("delivery:link", args=[world[key].pk])))
    out.append(teacher_client.get(reverse("delivery:list")))
    return out


def test_class_session_pages_have_no_external_urls_or_inline_code(
    client_for, teacher, world, monkeypatch
):
    # the share page prints the host's LAN address; pin it to loopback (an allowed host)
    monkeypatch.setattr(lan, "lan_ipv4_addresses", lambda: ["127.0.0.1"])
    responses = pages(client_for, teacher, world)
    assert len(responses) == 14
    for response in responses:
        assert response.status_code == 200, response.request["PATH_INFO"]
        html = response.content.decode()
        assert external_urls(html) == [], response.request["PATH_INFO"]
        assert csp_violations(html) == [], response.request["PATH_INFO"]


def test_link_page_has_suggestions_and_stays_clean(client_for, teacher, world):
    html = client_for(teacher).get(reverse("delivery:link", args=[world["plain"].pk])).content
    text = html.decode()
    assert "Suggestions:" in text and "Student 02" in text
    assert external_urls(text) == [] and csp_violations(text) == []


def test_new_scripts_are_plain_files_without_external_urls():
    for name in ("namepicker.js", "autosave.js", "share.js"):
        text = (STATIC / "js" / name).read_text(encoding="utf-8")
        assert external_urls(text) == [], name
        assert "eval(" not in text and "document.write" not in text, name


def test_class_pages_load_only_local_scripts(world):
    html = Client().get(f"/s/{world['class'].code}/").content.decode()
    assert "/static/js/namepicker.js" in html and "/static/js/autosave.js" in html
    assert "https://" not in html and "http://" not in html
