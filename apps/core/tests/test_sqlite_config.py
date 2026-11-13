"""KT-004: the SQLite setup the classroom depends on, tested on a real file (pytest's own test
database lives in memory, where WAL does not apply)."""

import copy
import threading

import pytest
from django.db import connection
from django.db.backends.sqlite3.base import DatabaseWrapper

# pytest-django blocks every database wrapper unless the test is marked; these tests only open
# their own wrappers on files in tmp_path and never touch the test database.
pytestmark = pytest.mark.django_db


def file_connection(path):
    settings_dict = copy.deepcopy(connection.settings_dict)
    settings_dict["NAME"] = str(path)
    return DatabaseWrapper(settings_dict)


def test_the_database_runs_in_wal_mode(tmp_path):
    db = file_connection(tmp_path / "wal.sqlite3")
    try:
        with db.cursor() as cursor:
            cursor.execute("PRAGMA journal_mode")
            assert cursor.fetchone()[0].lower() == "wal"
            cursor.execute("PRAGMA busy_timeout")
            assert cursor.fetchone()[0] >= 5000
    finally:
        db.close()


@pytest.mark.parametrize("threads", [20])
def test_concurrent_short_writes_never_report_a_locked_database(tmp_path, threads):
    path = tmp_path / "busy.sqlite3"
    setup = file_connection(path)
    with setup.cursor() as cursor:
        cursor.execute("CREATE TABLE hits (who INTEGER, n INTEGER)")
    setup.close()

    errors = []
    start = threading.Barrier(threads)

    def worker(who):
        db = file_connection(path)
        try:
            start.wait()
            db.set_autocommit(False)  # each insert is its own short write transaction
            for n in range(15):
                with db.cursor() as cursor:
                    cursor.execute("INSERT INTO hits VALUES (%s, %s)", [who, n])
                db.commit()
        except Exception as exc:  # noqa: BLE001 - the test reports whatever went wrong
            errors.append(f"{type(exc).__name__}: {exc}")
        finally:
            db.close()

    pool = [threading.Thread(target=worker, args=(i,)) for i in range(threads)]
    for t in pool:
        t.start()
    for t in pool:
        t.join()

    check = file_connection(path)
    with check.cursor() as cursor:
        cursor.execute("SELECT COUNT(*) FROM hits")
        total = cursor.fetchone()[0]
    check.close()
    assert not errors, errors[:3]
    assert total == threads * 15
