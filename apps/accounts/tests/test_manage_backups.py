"""The Backups page of the admin area: admins only, and only our own files can be downloaded."""

import sqlite3
from contextlib import closing

import pytest
from django.contrib.messages import get_messages
from django.urls import reverse

from apps.core import backup
from tests.test_offline import csp_violations, external_urls

pytestmark = pytest.mark.django_db


@pytest.fixture
def live(tmp_path, settings, monkeypatch):
    settings.DATA_DIR = tmp_path
    path = tmp_path / "db.sqlite3"
    with closing(sqlite3.connect(path)) as db:
        db.execute("CREATE TABLE django_migrations (id INTEGER)")
        db.commit()
    monkeypatch.setattr(backup, "database_path", lambda: path)
    return path


def urls(name="kt-20261116-101500-manual.sqlite3"):
    return [
        reverse("manage:backups"),
        reverse("manage:backup_create"),
        reverse("manage:backup_download", args=[name]),
    ]


@pytest.mark.parametrize("method", ["get", "post"])
def test_anonymous_is_sent_to_login_and_teachers_get_404(anon_client, teacher_c, live, method):
    for url in urls():
        response = getattr(anon_client, method)(url)
        assert response.status_code == 302
        assert response["Location"] == f"{reverse('accounts:login')}?next={url}"
        assert getattr(teacher_c, method)(url).status_code == 404
    assert backup.list_backups() == []


def test_admin_makes_lists_and_downloads_a_backup(admin_client, live):
    page = admin_client.get(reverse("manage:backups"))
    assert page.status_code == 200 and "No backups yet." in page.content.decode()

    response = admin_client.post(reverse("manage:backup_create"))
    assert response["Location"] == reverse("manage:backups")
    made = backup.list_backups()[0]
    assert [str(m) for m in get_messages(response.wsgi_request)] == [
        f"Backup “{made.name}” created."
    ]

    html = admin_client.get(reverse("manage:backups")).content.decode()
    assert reverse("manage:backup_download", args=[made.name]) in html
    assert "by hand" in html and str(backup.backup_dir()) in html
    assert f"manage.py restore {made.name}" in html
    assert external_urls(html) == [] and csp_violations(html) == []
    assert "<script" not in html

    download = admin_client.get(reverse("manage:backup_download", args=[made.name]))
    assert download.status_code == 200
    assert made.name in download["Content-Disposition"]
    assert b"".join(download.streaming_content) == made.path.read_bytes()


def test_backup_create_is_post_only(admin_client, live):
    assert admin_client.get(reverse("manage:backup_create")).status_code == 405
    assert backup.list_backups() == []


def test_download_serves_nothing_but_backups(admin_client, live):
    backup.create_backup("manual")
    (backup.backup_dir() / "secret.txt").write_text("x", encoding="utf-8")
    for name in ("secret.txt", "db.sqlite3", "kt-20000101-000000-manual.sqlite3", "..%2Fkt.toml"):
        assert admin_client.get(f"/manage/backups/{name}").status_code == 404


def test_without_a_database_file_the_page_explains_itself(admin_client):
    # The test database lives in memory: there is nothing to copy.
    html = admin_client.get(reverse("manage:backups")).content.decode()
    assert "Back up now" not in html
    response = admin_client.post(reverse("manage:backup_create"))
    assert [str(m) for m in get_messages(response.wsgi_request)] == [
        "There is no database file to back up."
    ]


def test_closing_a_session_makes_a_backup(admin_client, admin_user, live):
    from apps.delivery import services
    from apps.delivery.tests.conftest import make_revision

    sitting = services.create_sitting(
        revision=make_revision(admin_user), user=admin_user, title="7-A"
    )
    admin_client.post(reverse("delivery:close", args=[sitting.pk]))
    assert [b.reason for b in backup.list_backups()] == ["close"]


def test_the_overview_and_the_tabs_link_to_backups(admin_client):
    html = admin_client.get(reverse("manage:home")).content.decode()
    assert html.count(reverse("manage:backups")) == 2
