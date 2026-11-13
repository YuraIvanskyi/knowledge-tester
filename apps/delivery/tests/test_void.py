from decimal import Decimal

from apps.delivery import services
from apps.delivery.models import Attempt


def _finished_attempt(sitting):
    attempt = services.start_attempt(sitting, {"name": "Ann Lee"})
    services.finalize(attempt)
    attempt.refresh_from_db()
    return attempt


def test_void_changes_only_the_status(sitting):
    attempt = _finished_attempt(sitting)
    score = attempt.score

    assert services.void_attempt(attempt) is True

    attempt.refresh_from_db()
    assert attempt.status == Attempt.Status.VOIDED
    assert attempt.score == score
    assert attempt.taker == {"name": "Ann Lee"}


def test_void_is_idempotent(sitting):
    attempt = _finished_attempt(sitting)
    assert services.void_attempt(attempt) is True
    assert services.void_attempt(attempt) is False


def test_void_works_on_an_attempt_in_progress(sitting):
    attempt = services.start_attempt(sitting, {"name": "Ann Lee"})
    assert services.void_attempt(attempt) is True
    attempt.refresh_from_db()
    assert attempt.status == Attempt.Status.VOIDED
    assert attempt.score is None or isinstance(attempt.score, Decimal)


def test_voided_attempt_does_not_use_up_the_name_limit(sitting):
    attempt = _finished_attempt(sitting)
    assert services.attempts_used(sitting, "Ann Lee") == 1
    services.void_attempt(attempt)
    assert services.attempts_used(sitting, "Ann Lee") == 0
