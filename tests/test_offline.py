"""Offline guard (plan §5.2, §20.1): no external hosts, and nothing the CSP would block.

To cover more pages, add them to `page_responses`.
"""

import re
from pathlib import Path

import pytest
from django.urls import reverse

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
TEXT_SUFFIXES = {".css", ".js", ".mjs", ".svg", ".html", ".json", ".map", ".txt"}

URL_RE = re.compile(r"""(?:https?:)?//[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+[^\s"'<>)]*""")
# XML namespaces are identifiers, not network requests.
ALLOWED_PREFIXES = ("http://www.w3.org/",)
ALLOWED_HOSTS = ("localhost", "127.0.0.1")
TAG_RE = re.compile(r"<[^>]+>", re.S)


def external_urls(text: str) -> list[str]:
    bad = []
    for match in URL_RE.findall(text):
        if match.startswith(ALLOWED_PREFIXES):
            continue
        host = re.sub(r"^(?:https?:)?//", "", match).split("/")[0].split(":")[0]
        if host in ALLOWED_HOSTS:
            continue
        bad.append(match)
    return bad


def csp_violations(html: str) -> list[str]:
    problems = []
    if re.search(r"<style\b", html, re.I):
        problems.append("inline <style>")
    for tag in TAG_RE.findall(html):
        if re.search(r"\sstyle\s*=", tag, re.I):
            problems.append(f"style attribute in {tag[:60]}")
        if re.search(r"\son[a-z]+\s*=", tag, re.I):
            problems.append(f"inline event handler in {tag[:60]}")
    for tag in re.findall(r"<script\b[^>]*>", html, re.I):
        if not re.search(r"\ssrc\s*=", tag, re.I):
            problems.append("inline <script>")
    return problems


def page_responses(client, client_for, teacher):
    anon = [client.get(reverse("core:landing")), client.get(reverse("accounts:login"))]
    logged_in = client_for(teacher).get(reverse("core:dashboard"))
    return [*anon, logged_in]


def test_pages_have_no_external_urls_or_inline_code(client, client_for, teacher):
    for response in page_responses(client, client_for, teacher):
        assert response.status_code == 200
        html = response.content.decode()
        assert external_urls(html) == [], response.request["PATH_INFO"]
        assert csp_violations(html) == [], response.request["PATH_INFO"]


def test_csp_header_present(client):
    response = client.get(reverse("core:landing"))
    assert "default-src 'self'" in response["Content-Security-Policy"]


def test_static_files_have_no_external_urls():
    files = [p for p in STATIC_DIR.rglob("*") if p.is_file() and p.suffix in TEXT_SUFFIXES]
    assert files, "expected static files to scan"
    for path in files:
        text = path.read_text(encoding="utf-8", errors="ignore")
        assert external_urls(text) == [], str(path)


def test_css_has_no_remote_imports_or_fonts():
    for path in STATIC_DIR.rglob("*.css"):
        text = path.read_text(encoding="utf-8")
        assert "@import" not in text, str(path)
        assert "@font-face" not in text, str(path)


def test_base_css_stays_small():
    assert (STATIC_DIR / "css" / "base.css").stat().st_size < 15 * 1024


@pytest.mark.parametrize(
    "snippet",
    [
        '<script src="https://cdn.example.com/x.js"></script>',
        '<link rel="stylesheet" href="//fonts.googleapis.com/css">',
    ],
)
def test_guard_detects_external_urls(snippet):
    assert external_urls(snippet)


@pytest.mark.parametrize(
    "snippet",
    ["<style>a{}</style>", '<p style="color:red">', "<script>1</script>", '<a onclick="x()">'],
)
def test_guard_detects_csp_violations(snippet):
    assert csp_violations(snippet)


def test_guard_allows_svg_namespace_and_external_scripts():
    assert external_urls('<svg xmlns="http://www.w3.org/2000/svg">') == []
    assert csp_violations('<script src="/static/js/a.js"></script>') == []
