"""The Help page: the AI prompt, ready to copy, cut out of the prompt file in docs/."""

from pathlib import Path

import pytest
from django.urls import reverse

from apps.core import prompts
from tests.test_offline import csp_violations, external_urls

ROOT = Path(__file__).resolve().parents[3]


def test_the_prompt_file_gives_one_prompt_and_its_follow_ups():
    pack = prompts.parse((ROOT / prompts.PROMPT_FILE).read_text(encoding="utf-8"))
    assert pack.prompt.startswith("Ти досвідчений учитель")
    assert pack.prompt.rstrip().endswith("JSON валідний.")
    for part in ("ПАРАМЕТРИ ТЕСТУ", "Кількість варіантів", '"variants"', "```json"):
        assert part in pack.prompt
    assert "````" not in pack.prompt
    titles = [f.title for f in pack.follow_ups]
    assert len(titles) == 4 and titles[0].startswith("Ключ")
    assert any("варіант" in t for t in titles)
    for follow_up in pack.follow_ups:
        assert follow_up.text and "```" not in follow_up.text and not follow_up.title.endswith(":")


def test_parse_survives_windows_line_endings_and_junk():
    text = (ROOT / prompts.PROMPT_FILE).read_text(encoding="utf-8")
    windows = prompts.parse(text.replace("\n", "\r\n"))
    assert windows == prompts.parse(text)
    empty = prompts.parse("# nothing to see\n\njust text")
    assert empty.prompt == "" and empty.follow_ups == []


@pytest.mark.django_db
def test_help_needs_a_login(client):
    response = client.get(reverse("core:help"))
    assert response.status_code == 302 and "/accounts/login/" in response["Location"]


@pytest.mark.django_db
def test_help_page_offers_the_prompt_to_copy(teacher_client):
    response = teacher_client.get(reverse("core:help"))
    assert response.status_code == 200
    html = response.content.decode()
    pack = prompts.textbook_prompt()
    assert response.context["pack"].prompt == pack.prompt
    assert '<textarea id="prompt-main"' in html and "readonly" in html
    assert "ПАРАМЕТРИ ТЕСТУ" in html and "Кількість варіантів" in html
    assert 'data-copy="prompt-main"' in html and "/static/js/copy.js" in html
    # every follow-up has its own box and button
    for number in range(1, len(pack.follow_ups) + 1):
        assert f'id="prompt-{number}"' in html and f'data-copy="prompt-{number}"' in html
    assert reverse("assessments:import") in html
    # quotes of the JSON example arrive escaped, not as markup
    assert "&quot;format&quot;: &quot;knowledge-tester/test&quot;" in html
    assert external_urls(html) == [] and csp_violations(html) == []


@pytest.mark.django_db
def test_help_is_in_the_menu_and_linked_from_the_import_page(teacher_client):
    help_url = reverse("core:help")
    dashboard = teacher_client.get(reverse("core:dashboard")).content.decode()
    assert f'<a href="{help_url}">Help</a>' in dashboard
    page = teacher_client.get(help_url).content.decode()
    assert f'<a href="{help_url}" aria-current="page">Help</a>' in page
    importer = teacher_client.get(reverse("assessments:import")).content.decode()
    assert f'<a href="{help_url}">Help</a> page' in importer


@pytest.mark.django_db
def test_a_missing_prompt_file_is_said_plainly(teacher_client, monkeypatch):
    monkeypatch.setattr(prompts, "textbook_prompt", lambda: prompts.PromptPack())
    html = teacher_client.get(reverse("core:help")).content.decode()
    assert "The prompt file was not found" in html and "prompt-main" not in html


def test_copy_script_works_without_the_clipboard_api():
    js = (ROOT / "static" / "js" / "copy.js").read_text(encoding="utf-8")
    # plain HTTP on the LAN: the old command first, the Clipboard API only as a fallback
    assert js.index('execCommand("copy")') < js.index("navigator.clipboard")
    assert "isSecureContext" in js
