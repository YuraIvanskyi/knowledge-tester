"""Offline / CSP guard for the roster pages (KT-602): no external hosts, nothing the CSP blocks."""

import re
from pathlib import Path

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from apps.people.models import Group, Student
from tests.test_offline import csp_violations, external_urls

pytestmark = pytest.mark.django_db

TEMPLATES = Path(__file__).resolve().parent.parent / "templates" / "people" / "roster"


def roster_responses(client, teacher):
    group = Group.objects.create(owner=teacher, name="7-А")
    Group.objects.create(owner=teacher, name="Минулий", is_archived=True)
    student = Student.objects.create(
        owner=teacher, group=group, full_name="Іваненко Дем’ян", pin="4821"
    )
    Student.objects.create(owner=teacher, group=group, full_name="Без Піна")
    Student.objects.create(owner=teacher, full_name="Без Групи")

    pages = [
        reverse("people:groups"),
        reverse("people:groups") + "?archived=1",
        reverse("people:group_create"),
        reverse("people:group", args=[group.pk]),
        reverse("people:group_edit", args=[group.pk]),
        reverse("people:group_delete", args=[group.pk]),
        reverse("people:group_pins", args=[group.pk]),
        reverse("people:students"),
        reverse("people:students") + "?q=іван&group=none",
        reverse("people:student_create") + f"?group={group.pk}",
        reverse("people:student_edit", args=[student.pk]),
        reverse("people:import") + f"?group={group.pk}",
    ]
    responses = [client.get(url) for url in pages]

    # POST-rendered pages: regenerate-PINs confirmation, duplicate warning, import errors/preview
    responses.append(client.post(reverse("people:group_pins", args=[group.pk]), {"mode": "all"}))
    responses.append(
        client.post(
            reverse("people:student_create"), {"full_name": "дем'ян іваненко", "group": group.pk}
        )
    )
    responses.append(client.post(reverse("people:import"), {"text": ""}))
    responses.append(
        client.post(
            reverse("people:import"),
            {"text": "x", "file": SimpleUploadedFile("a.csv", b"Name\nX Y")},
        )
    )
    redirect = client.post(
        reverse("people:import"),
        {"text": "Іваненко Дем'ян; 7-А\nНовий Учень; Нова\n12345\nНовий Учень"},
    )
    responses.append(client.get(redirect["Location"]))
    # an all-invalid preview and an empty group page
    client.post(reverse("people:import"), {"text": "12345"})
    responses.append(client.get(reverse("people:import") + "?step=preview"))
    empty = Group.objects.create(owner=teacher, name="Порожня")
    responses.append(client.get(reverse("people:group", args=[empty.pk])))
    responses.append(client.get(reverse("people:group_pins", args=[empty.pk])))
    return responses


def test_roster_pages_have_no_external_urls_or_inline_code(client_for, teacher):
    client = client_for(teacher)
    responses = roster_responses(client, teacher)
    assert len(responses) >= 20
    for response in responses:
        assert response.status_code == 200, response.request["PATH_INFO"]
        html = response.content.decode()
        assert external_urls(html) == [], response.request["PATH_INFO"]
        assert csp_violations(html) == [], response.request["PATH_INFO"]
        assert "people.css" in html


def test_roster_pages_send_the_csp_header(client_for, teacher):
    response = client_for(teacher).get(reverse("people:groups"))
    assert "default-src 'self'" in response["Content-Security-Policy"]


def test_roster_templates_have_no_inline_style_script_or_handlers():
    templates = sorted(TEMPLATES.glob("*.html"))
    assert len(templates) >= 10
    for path in templates:
        source = path.read_text(encoding="utf-8")
        assert csp_violations(source) == [], path.name
        assert external_urls(source) == [], path.name
        assert not re.search(r"<script\b", source, re.I), path.name


def test_people_stylesheet_has_no_remote_resources():
    css = (Path(__file__).resolve().parent.parent / "static" / "css" / "people.css").read_text(
        encoding="utf-8"
    )
    assert external_urls(css) == []
    assert "@import" not in css and "@font-face" not in css and "url(" not in css


def test_roster_pages_put_the_sub_tabs_directly_under_the_top_bar(client_for, teacher):
    responses = roster_responses(client_for(teacher), teacher)
    checked = 0
    for response in responses:
        html = response.content.decode()
        if 'class="subnav"' in html:
            assert html.index('class="subnav"') < html.index("<h1"), response.request["PATH_INFO"]
            checked += 1
    assert checked >= 10


def test_roster_tables_use_the_card_pattern(client_for, teacher):
    client = client_for(teacher)
    group = Group.objects.create(owner=teacher, name="7-А")
    Student.objects.create(owner=teacher, group=group, full_name="Іваненко Дем’ян", pin="4821")
    for name in ("people:groups", "people:students"):
        html = client.get(reverse(name)).content.decode()
        assert "table-compact" in html and html.count("cell-title") >= 1, name
    for name in ("people:group", "people:group_pins"):
        html = client.get(reverse(name, args=[group.pk])).content.decode()
        assert "table-compact" in html and html.count("cell-title") == 1, name
    redirect = client.post(reverse("people:import"), {"text": "Іваненко Дем'ян; 7-А\nНовий; Нова"})
    html = client.get(redirect["Location"]).content.decode()
    assert "import-table" in html and html.count("cell-title") == 2
    assert 'label class="tap"' in html


def test_group_page_button_opens_the_chooser_for_the_group(client_for, teacher):
    group = Group.objects.create(owner=teacher, name="7-А")
    Student.objects.create(owner=teacher, group=group, full_name="Іваненко Дем’ян")
    html = client_for(teacher).get(reverse("people:group", args=[group.pk])).content.decode()
    link = reverse("delivery:pick") + f"?group={group.pk}"
    assert f'class="btn btn-primary" href="{link}"' in html


def test_people_stylesheet_keeps_no_copy_of_the_shared_rules():
    css = (Path(__file__).resolve().parent.parent / "static" / "css" / "people.css").read_text(
        encoding="utf-8"
    )
    manage = (Path(__file__).resolve().parent.parent / "static" / "css" / "manage.css").read_text(
        encoding="utf-8"
    )
    for text in (css, manage):
        assert not re.search(r"^\.subnav\b", text, re.M)
        assert not re.search(r"^\.tap\b", text, re.M)
        assert "[hidden] {" not in text
