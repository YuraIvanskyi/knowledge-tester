"""Database backups (plan §19.4): copies of the SQLite file in <data folder>/backups/.

A backup is made with SQLite's online backup API, so it is safe while the server is running and
includes whatever still sits in the WAL file. Backups happen when the server starts, when a
session is closed, and on demand (``manage.py backup``, or the Backups page in /manage/).
Only the newest ``KEEP`` files are kept. There is no media to back up yet (question images are
not implemented), so the database file is everything.
"""

from __future__ import annotations

import logging
import re
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from django.conf import settings
from django.db import connection

logger = logging.getLogger(__name__)

KEEP = 20
# Reasons end up in the file name, so the list of backups explains itself.
REASONS = ("start", "close", "manual", "restore")
NAME_RE = re.compile(r"^kt-\d{8}-\d{6}(-\d+)?-(start|close|manual|restore)\.sqlite3$")


class BackupError(Exception):
    """The backup or restore could not be done; the message is safe to show to an admin."""


@dataclass(frozen=True)
class Backup:
    path: Path
    created: datetime  # local time, from the file's modification time
    size: int

    @property
    def name(self) -> str:
        return self.path.name

    @property
    def reason(self) -> str:
        return self.path.stem.rsplit("-", 1)[-1]


def backup_dir() -> Path:
    return Path(settings.DATA_DIR) / "backups"


def database_path() -> Path | None:
    """The database file, or None when the database is not a file (the in-memory test database)."""
    name = str(connection.settings_dict["NAME"])
    if not name or ":memory:" in name or name.startswith("file:"):
        return None
    return Path(name)


def is_backup_name(name: str) -> bool:
    return bool(NAME_RE.match(name))


def list_backups() -> list[Backup]:
    """Newest first."""
    folder = backup_dir()
    if not folder.is_dir():
        return []
    found = []
    for path in folder.iterdir():
        if path.is_file() and is_backup_name(path.name):
            stat = path.stat()
            found.append(Backup(path, datetime.fromtimestamp(stat.st_mtime), stat.st_size))
    found.sort(key=lambda b: (b.created, b.name), reverse=True)
    return found


def find_backup(name: str) -> Backup | None:
    """A backup by its file name; anything that is not one of our file names is never looked up."""
    if not is_backup_name(name):
        return None
    for backup in list_backups():
        if backup.name == name:
            return backup
    return None


def newest_age() -> timedelta | None:
    backups = list_backups()
    return datetime.now() - backups[0].created if backups else None


def _free_path(folder: Path, reason: str) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = folder / f"kt-{stamp}-{reason}.sqlite3"
    counter = 2
    while path.exists():  # two backups within one second
        path = folder / f"kt-{stamp}-{counter}-{reason}.sqlite3"
        counter += 1
    return path


def _copy_database(source: Path, target: Path) -> None:
    with (
        closing(sqlite3.connect(source, timeout=10)) as src,
        closing(sqlite3.connect(target)) as dst,
    ):
        src.backup(dst)


def _check_database(path: Path) -> None:
    """Raise BackupError unless ``path`` is a readable, intact SQLite database of this app."""
    try:
        with closing(sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)) as db:
            result = db.execute("PRAGMA integrity_check").fetchone()
            tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master")}
    except sqlite3.Error as error:
        raise BackupError(f"{path.name} is not a readable database: {error}") from error
    if not result or result[0] != "ok":
        raise BackupError(f"{path.name} is damaged (integrity check failed).")
    if "django_migrations" not in tables:
        raise BackupError(f"{path.name} is not a Knowledge Tester database.")


def prune(keep: int = KEEP) -> int:
    """Delete all but the newest ``keep`` backups. Returns how many were deleted."""
    removed = 0
    for backup in list_backups()[keep:]:
        try:
            backup.path.unlink()
            removed += 1
        except OSError as error:
            logger.warning("Could not delete old backup %s: %s", backup.name, error)
    return removed


def create_backup(reason: str = "manual") -> Backup | None:
    """Copy the database into the backups folder. Returns None when there is nothing to copy
    (no database file yet, or an in-memory database)."""
    if reason not in REASONS:
        raise ValueError(reason)
    source = database_path()
    if source is None or not source.exists():
        return None
    folder = backup_dir()
    try:
        folder.mkdir(parents=True, exist_ok=True)
        target = _free_path(folder, reason)
        partial = target.with_suffix(".partial")
        _copy_database(source, partial)
        partial.replace(target)
    except (OSError, sqlite3.Error) as error:
        raise BackupError(f"The backup failed: {error}") from error
    prune()
    stat = target.stat()
    return Backup(target, datetime.fromtimestamp(stat.st_mtime), stat.st_size)


def backup_quietly(reason: str) -> Backup | None:
    """For automatic backups inside a request: a failure is logged, never shown to the user."""
    try:
        return create_backup(reason)
    except Exception:  # noqa: BLE001 - closing a session must not fail because of a backup
        logger.exception("Automatic backup (%s) failed", reason)
        return None


def restore_backup(source: Path) -> Backup | None:
    """Replace the database with the content of ``source``. Run it while the server is stopped.

    The current database is backed up first (reason "restore") and returned, so a restore can
    itself be undone.
    """
    source = Path(source)
    if not source.is_file():
        raise BackupError(f"File not found: {source}")
    _check_database(source)
    target = database_path()
    if target is None:
        raise BackupError("This database is not a file; nothing to restore into.")
    if source.resolve() == target.resolve():
        raise BackupError("That file is the live database itself.")
    safety = create_backup("restore")
    connection.close()
    try:
        # The backup API writes through SQLite, so the WAL file of the live database stays valid.
        _copy_database(source, target)
    except sqlite3.Error as error:
        raise BackupError(
            f"The restore failed: {error}. Is the server still running? Stop it and try again."
        ) from error
    return safety
