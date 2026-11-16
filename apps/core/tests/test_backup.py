"""Backups (plan §19.4): on a real SQLite file in tmp_path, never the test database."""

import os
import sqlite3
import time
from contextlib import closing
from datetime import timedelta
from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.core import backup
from apps.core.management.commands.serve import Command as ServeCommand


def make_db(path, marker="one"):
    with closing(sqlite3.connect(path)) as db:
        db.execute("CREATE TABLE IF NOT EXISTS django_migrations (id INTEGER)")
        db.execute("CREATE TABLE IF NOT EXISTS notes (text TEXT)")
        db.execute("DELETE FROM notes")
        db.execute("INSERT INTO notes VALUES (?)", (marker,))
        db.commit()
    return path


def read_marker(path):
    with closing(sqlite3.connect(path)) as db:
        return db.execute("SELECT text FROM notes").fetchone()[0]


@pytest.fixture
def live(tmp_path, settings, monkeypatch):
    """A data folder with a live database file."""
    settings.DATA_DIR = tmp_path
    path = make_db(tmp_path / "db.sqlite3")
    monkeypatch.setattr(backup, "database_path", lambda: path)
    return path


def test_the_test_database_is_never_backed_up():
    assert backup.database_path() is None
    assert backup.create_backup("close") is None


def test_backup_copies_the_data_and_names_the_reason(live):
    made = backup.create_backup("close")
    assert made.path.parent == backup.backup_dir()
    assert backup.is_backup_name(made.name) and made.reason == "close"
    assert read_marker(made.path) == "one"
    assert [b.name for b in backup.list_backups()] == [made.name]
    assert not list(backup.backup_dir().glob("*.partial"))


def test_backup_sees_rows_that_are_still_in_the_wal(live):
    writer = sqlite3.connect(live)
    try:
        writer.execute("PRAGMA journal_mode=WAL")
        writer.execute("UPDATE notes SET text = 'in the wal'")
        writer.commit()  # the connection stays open: nothing is checkpointed yet
        assert read_marker(backup.create_backup("manual").path) == "in the wal"
    finally:
        writer.close()


def test_two_backups_in_one_second_get_different_names(live):
    names = {backup.create_backup("manual").name for _n in range(3)}
    assert len(names) == 3
    assert all(backup.is_backup_name(n) for n in names)


def test_only_the_newest_are_kept(live, monkeypatch):
    monkeypatch.setattr(backup, "KEEP", 3)
    made = []
    for index in range(5):
        item = backup.create_backup("manual")
        stamp = time.time() - 1000 + index  # distinct, increasing modification times
        os.utime(item.path, (stamp, stamp))
        made.append(item.name)
        backup.prune(3)
    assert [b.name for b in backup.list_backups()] == made[:1:-1]


def test_no_database_file_means_no_backup(tmp_path, settings, monkeypatch):
    settings.DATA_DIR = tmp_path
    monkeypatch.setattr(backup, "database_path", lambda: tmp_path / "missing.sqlite3")
    assert backup.create_backup("start") is None
    assert backup.list_backups() == []


def test_unknown_reason_is_a_programming_error(live):
    with pytest.raises(ValueError):
        backup.create_backup("../evil")


@pytest.mark.parametrize(
    "name",
    [
        "../db.sqlite3",
        "db.sqlite3",
        "kt-20261116-101500-manual.sqlite3.bak",
        "kt-20261116-101500-evil.sqlite3",
        "..\\kt-20261116-101500-manual.sqlite3",
        "",
    ],
)
def test_only_our_own_file_names_are_looked_up(live, name):
    backup.create_backup("manual")
    assert backup.find_backup(name) is None


def test_other_files_in_the_folder_are_not_listed(live):
    made = backup.create_backup("manual")
    (backup.backup_dir() / "notes.txt").write_text("x", encoding="utf-8")
    assert [b.name for b in backup.list_backups()] == [made.name]


def test_restore_brings_the_old_data_back_and_keeps_the_replaced_one(live):
    old = backup.create_backup("manual")
    make_db(live, "two")
    safety = backup.restore_backup(old.path)
    assert read_marker(live) == "one"
    assert safety.reason == "restore" and read_marker(safety.path) == "two"


def test_restore_refuses_files_that_are_not_our_database(live, tmp_path):
    junk = tmp_path / "junk.sqlite3"
    junk.write_bytes(b"this is not a database at all" * 50)
    foreign = tmp_path / "foreign.sqlite3"
    with closing(sqlite3.connect(foreign)) as db:
        db.execute("CREATE TABLE something (id INTEGER)")
        db.commit()
    for path in (junk, foreign, tmp_path / "missing.sqlite3", live):
        with pytest.raises(backup.BackupError):
            backup.restore_backup(path)
    assert read_marker(live) == "one"


def test_backup_command(live):
    out = StringIO()
    call_command("backup", stdout=out)
    assert "Backup written" in out.getvalue()
    assert len(backup.list_backups()) == 1


def test_backup_command_without_a_database(tmp_path, settings, monkeypatch):
    settings.DATA_DIR = tmp_path
    monkeypatch.setattr(backup, "database_path", lambda: tmp_path / "missing.sqlite3")
    out = StringIO()
    call_command("backup", stdout=out)
    assert "nothing to back up" in out.getvalue()


def test_restore_command_by_name_and_listing(live):
    made = backup.create_backup("manual")
    make_db(live, "two")
    out = StringIO()
    call_command("restore", "--list", stdout=out)
    assert made.name in out.getvalue()
    call_command("restore", made.name, "--yes", stdout=out)
    assert read_marker(live) == "one"
    assert "Restored from" in out.getvalue()


def test_restore_command_needs_a_known_file(live):
    with pytest.raises(CommandError):
        call_command("restore", "kt-20000101-000000-manual.sqlite3", "--yes", stdout=StringIO())
    with pytest.raises(CommandError):
        call_command("restore", stdout=StringIO())  # no file named: lists, then stops


def test_restore_command_asks_before_replacing(live, monkeypatch):
    made = backup.create_backup("manual")
    make_db(live, "two")
    monkeypatch.setattr("builtins.input", lambda _prompt: "no")
    with pytest.raises(CommandError):
        call_command("restore", made.name, stdout=StringIO())
    assert read_marker(live) == "two"


def test_serve_backs_up_once_per_start_not_per_restart(live):
    out = StringIO()
    ServeCommand(stdout=out)._backup_at_start()
    assert [b.reason for b in backup.list_backups()] == ["start"]
    ServeCommand(stdout=out)._backup_at_start()  # a restart a moment later
    assert len(backup.list_backups()) == 1
    old = time.time() - timedelta(hours=1).total_seconds()
    os.utime(backup.list_backups()[0].path, (old, old))
    ServeCommand(stdout=out)._backup_at_start()
    assert len(backup.list_backups()) == 2


def test_a_failing_automatic_backup_never_raises(live, monkeypatch):
    def boom(_source, _target):
        raise sqlite3.OperationalError("disk full")

    monkeypatch.setattr(backup, "_copy_database", boom)
    assert backup.backup_quietly("close") is None
    with pytest.raises(backup.BackupError):
        backup.create_backup("manual")
