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


def switchers(html: str) -> list[str]:
    return re.findall(r'<form class="lang-switch[^"]*".*?</form>', html, re.S)


def test_switcher_is_in_header_and_footer_with_abbreviations(client):
    html = client.get(reverse("core:landing")).content.decode()
    header, footer = switchers(html)
    assert "lang-switch-header" in header and "lang-switch-footer" in footer
    assert html.index(header) < html.index("<main") < html.index(footer)
    for form in (header, footer):
        assert reverse("set_language") in form
        assert "csrfmiddlewaretoken" in form
        assert 'name="next" value="/"' in form
        assert 'value="uk"' in form and ">UA<" in form
        assert 'value="en"' in form and ">ENG<" in form
        # Full names stay available to screen readers and as tooltips, untranslated.
        assert 'aria-label="Українська"' in form and 'aria-label="English"' in form
    # Labels are the same in every UI language.
    client.cookies[LANG_COOKIE] = "en"
    for form in switchers(client.get("/").content.decode()):
        assert ">UA<" in form and ">ENG<" in form and 'aria-label="Language"' in form


def test_switcher_marks_current_language_in_both_places(client):
    for form in switchers(client.get("/").content.decode()):
        assert re.search(r'value="uk"[^>]*aria-current="true"', form)
    client.cookies[LANG_COOKIE] = "en"
    for form in switchers(client.get("/").content.decode()):
        assert re.search(r'value="en"[^>]*aria-current="true"', form)


def test_css_shows_header_switcher_on_desktop_and_footer_on_phones():
    css = (settings.BASE_DIR / "static" / "css" / "base.css").read_text(encoding="utf-8")
    assert re.search(r"\.lang-switch-header\s*\{\s*display:\s*none", css)
    media = css[css.index("@media (min-width: 640px)") :]
    assert ".lang-switch-header" in media and ".site-footer" in media


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
