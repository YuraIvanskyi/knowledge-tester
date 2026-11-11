"""Ukrainian is the default UI language; the footer switcher and the cookie change it."""

import re

import pytest
from django.conf import settings
from django.urls import reverse
from django.utils import translation

from apps.core import i18n_tools

LANG_COOKIE = settings.LANGUAGE_COOKIE_NAME


@pytest.fixture(autouse=True)
def default_is_ukrainian(settings):
    # The pytest settings default to English (so old tests assert English); these tests exercise
    # the production default.
    settings.LANGUAGE_CODE = "uk"


def html_lang(response) -> str:
    return re.search(r'<html lang="([^"]+)"', response.content.decode()).group(1)


def test_fresh_client_gets_ukrainian_even_with_english_browser(client):
    response = client.get(reverse("core:landing"), headers={"Accept-Language": "en"})
    assert html_lang(response) == "uk"
    with translation.override("uk"):
        skip = translation.gettext("Skip to content")
    assert skip != "Skip to content"
    assert skip in response.content.decode()
    assert response["Content-Language"] == "uk"


def test_language_cookie_beats_default_and_accept_language(client):
    client.cookies[LANG_COOKIE] = "en"
    response = client.get(reverse("core:landing"), headers={"Accept-Language": "uk"})
    assert html_lang(response) == "en"
    assert "Skip to content" in response.content.decode()


def test_unsupported_accept_language_falls_back_to_default(client):
    response = client.get(reverse("core:landing"), headers={"Accept-Language": "de,fr;q=0.8"})
    assert html_lang(response) == "uk"


def test_set_language_switches_to_english_and_back(client):
    landing = reverse("core:landing")
    response = client.post(reverse("set_language"), {"language": "en", "next": landing})
    assert response.status_code == 302
    assert response["Location"] == landing
    assert client.cookies[LANG_COOKIE].value == "en"
    assert html_lang(client.get(landing, headers={"Accept-Language": "uk"})) == "en"

    client.post(reverse("set_language"), {"language": "uk", "next": landing})
    assert client.cookies[LANG_COOKIE].value == "uk"
    assert html_lang(client.get(landing, headers={"Accept-Language": "en"})) == "uk"


def test_set_language_ignores_external_next(client):
    response = client.post(
        reverse("set_language"), {"language": "en", "next": "https://evil.example/"}
    )
    assert response.status_code == 302
    assert "evil.example" not in response["Location"]


def test_footer_switcher_lists_both_languages_untranslated(client):
    html = client.get(reverse("core:landing")).content.decode()
    form = re.search(r'<form class="lang-switch".*?</form>', html, re.S).group(0)
    assert reverse("set_language") in form
    assert "csrfmiddlewaretoken" in form
    assert 'name="next" value="/"' in form
    assert 'value="uk"' in form and ">Українська<" in form
    assert 'value="en"' in form and ">English<" in form
    # Switcher labels are endonyms: identical in both languages.
    client.cookies[LANG_COOKIE] = "en"
    form_en = re.search(
        r'<form class="lang-switch".*?</form>', client.get("/").content.decode(), re.S
    ).group(0)
    assert ">Українська<" in form_en and ">English<" in form_en


def test_ukrainian_plural_forms():
    """Builtin Django strings (uk catalog shipped with Django) select the three forms."""
    with translation.override("uk"):
        forms = {
            n: translation.ngettext("%(num)d year", "%(num)d years", n)
            for n in (1, 2, 5, 11, 21, 22, 25, 101, 111)
        }
    one, few, many = forms[1], forms[2], forms[5]
    assert len({one, few, many}) == 3
    assert forms[11] == many and forms[25] == many and forms[111] == many
    assert forms[21] == one and forms[101] == one
    assert forms[22] == few


def test_project_catalog_header_has_ukrainian_plural_rule():
    po = i18n_tools.polib.pofile(str(i18n_tools.po_path("uk")))
    assert po.metadata["Language"] == "uk"
    assert po.metadata["Plural-Forms"] == i18n_tools.PLURAL_FORMS["uk"]


def test_project_catalog_is_compiled_and_used():
    assert i18n_tools.mo_path("uk").exists()
    with translation.override("uk"):
        assert translation.gettext("Language") == "Мова"
    with translation.override("en"):
        assert translation.gettext("Language") == "Language"


def test_catalog_is_complete_and_consistent():
    """Every extracted UI string has a Ukrainian translation with matching placeholders."""
    from apps.core import i18n_tools

    assert i18n_tools.check() == []
