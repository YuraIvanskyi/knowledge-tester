"""Delivery logic that is independent of HTTP: codes, shuffling, answers, finalising."""

from __future__ import annotations

import logging
import random
import secrets
from datetime import timedelta

from django.db import IntegrityError, transaction
from django.utils import timezone
from django.utils.translation import gettext

from .models import CODE_ALPHABET, CODE_LENGTH, Answer, Attempt, Sitting

logger = logging.getLogger(__name__)

CHOICE_TYPES = ("single_choice", "multiple_choice", "choose_n")
TEXT_TYPES = ("short_answer", "open")
# A submit that arrives slightly after the deadline (network latency, client clock) still counts.
SUBMIT_GRACE = timedelta(seconds=20)
MAX_TEXT_LENGTH = 10_000


# --- session codes -----------------------------------------------------------------------------


def normalize_code(raw: str) -> str:
    return "".join((raw or "").split()).upper()


def generate_code() -> str:
    return "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))


def create_sitting(
    *, revision, user, title: str, access_code: str = "", group=None, use_pin: bool = False
) -> Sitting:
    """Create a sitting with a unique code (retries on the rare collision).

    `group` makes it a group-bound session (the caller has checked the group is the user's own);
    `use_pin` only means something with a group, so it is dropped without one."""
    for _ in range(20):
        try:
            with transaction.atomic():
                return Sitting.objects.create(
                    revision=revision,
                    code=generate_code(),
                    title=title,
                    access_code=access_code,
                    group=group,
                    use_pin=bool(use_pin and group is not None),
                    created_by=user,
                )
        except IntegrityError:
            continue
    raise RuntimeError("Could not generate a unique session code")


def can_manage(user, sitting: Sitting) -> bool:
    return user.is_authenticated and (user.is_admin_role or sitting.created_by_id == user.pk)


# --- test document helpers ---------------------------------------------------------------------


def question_map(test: dict) -> dict[str, dict]:
    return {q["id"]: q for q in test.get("questions", [])}


def time_limit_minutes(test: dict) -> int | None:
    return (test.get("settings") or {}).get("time_limit_minutes") or None


def taker_fields(test: dict) -> list[dict]:
    fields = test.get("taker_fields")
    if fields is None:
        fields = [{"key": "name", "label": gettext("Full name"), "required": True}]
    return fields


def normalize_name(value: str) -> str:
    return " ".join((value or "").split()).casefold()


def taker_display(attempt: Attempt, fields: list[dict]) -> str:
    """A short label for a taker in tables: the name, else the first filled field."""
    values = attempt.taker or {}
    if values.get("name"):
        return values["name"]
    for field in fields:
        if values.get(field["key"]):
            return values[field["key"]]
    return "-"


def shuffled_orders(test: dict, seed: str) -> tuple[list[str], dict[str, list[str]]]:
    """Question order and per-question option order, generated once per attempt (seeded)."""
    rng = random.Random(seed)
    settings = test.get("settings") or {}
    questions = test.get("questions", [])
    order = [q["id"] for q in questions]
    if settings.get("shuffle_questions"):
        rng.shuffle(order)
    option_orders: dict[str, list[str]] = {}
    for q in questions:
        if q["type"] in CHOICE_TYPES:
            ids = [o["id"] for o in q.get("options", [])]
            if settings.get("shuffle_options"):
                rng.shuffle(ids)
            option_orders[q["id"]] = ids
    return order, option_orders


def start_attempt(sitting: Sitting, taker: dict, token=None, student=None) -> Attempt:
    """Create an attempt. `token` lets the page that was shown to the taker (and shuffled with
    that token) become the attempt without re-shuffling. Starting twice with the same token (a
    repeated autosave that overtook the first response, a double tap) returns the attempt that
    already exists instead of making a second one. A token that belongs to another session is
    ignored. `student` is the roster student picked in a group-bound session."""
    if token is not None:
        existing = Attempt.objects.filter(token=token).first()
        if existing is not None:
            if existing.sitting_id == sitting.pk:
                return existing
            token = None  # somebody else's token: shuffle with a fresh one
    test = sitting.revision.test
    attempt = Attempt(sitting=sitting, taker=taker, student=student)
    if token is not None:
        attempt.token = token
    attempt.question_order, attempt.option_orders = shuffled_orders(test, str(attempt.token))
    minutes = time_limit_minutes(test)
    try:
        with transaction.atomic():
            attempt.save()
            if minutes:
                attempt.deadline_at = attempt.started_at + timedelta(minutes=minutes)
                attempt.save(update_fields=["deadline_at"])
    except IntegrityError:
        # Two requests with one token hit the insert together: the loser takes the winner's.
        winner = Attempt.objects.filter(token=attempt.token, sitting=sitting).first()
        if winner is None:
            raise
        return winner
    return attempt


def attempts_used(sitting: Sitting, name: str) -> int:
    """Attempts already made in this session by the same normalised name (soft limit)."""
    key = normalize_name(name)
    if not key:
        return 0
    rows = sitting.attempts.exclude(status=Attempt.Status.VOIDED).values_list("taker", flat=True)
    return sum(1 for taker in rows if normalize_name((taker or {}).get("name", "")) == key)


# --- answers -----------------------------------------------------------------------------------


def clean_value(question: dict, raw):
    """Coerce a posted value to the stored shape; None means 'no answer'."""
    if question["type"] in CHOICE_TYPES:
        if isinstance(raw, str):
            raw = [raw]
        valid = {o["id"] for o in question.get("options", [])}
        picked = [v for v in (raw or []) if isinstance(v, str) and v in valid]
        picked = list(dict.fromkeys(picked))
        if question["type"] == "single_choice":
            picked = picked[:1]
        elif question["type"] == "choose_n" and isinstance(question.get("n"), int):
            picked = picked[: question["n"]]  # server-side cap: never trust the client
        return picked or None
    if isinstance(raw, list):
        raw = raw[0] if raw else ""
    text = str(raw or "").strip()[:MAX_TEXT_LENGTH]
    return text or None


def save_answers(attempt: Attempt, test: dict, values: dict[str, object]) -> None:
    """Upsert answers for the given question ids; an empty value removes the row."""
    questions = question_map(test)
    for qid, raw in values.items():
        question = questions.get(qid)
        if question is None:
            continue
        value = clean_value(question, raw)
        if value is None:
            Answer.objects.filter(attempt=attempt, question_key=qid).delete()
        else:
            Answer.objects.update_or_create(
                attempt=attempt, question_key=qid, defaults={"value": value}
            )


def answered_ids(attempt: Attempt) -> set[str]:
    return set(attempt.answers.exclude(value__isnull=True).values_list("question_key", flat=True))


# --- finalising --------------------------------------------------------------------------------


def grade(attempt: Attempt) -> None:
    """Call the grading service (late import: it is owned by another workstream)."""
    from apps.grading.service import grade_attempt

    try:
        grade_attempt(attempt)
    except Exception:
        logger.exception("Grading failed for attempt %s", attempt.pk)


def finalize(attempt: Attempt, status: str = Attempt.Status.SUBMITTED) -> bool:
    """Finish an in-progress attempt exactly once and grade it. Returns True if it changed."""
    # One transaction for the flip and the grading: a second request that loses the race waits for
    # the write lock, then sees an attempt that is already graded (the done page needs the score).
    with transaction.atomic():
        changed = Attempt.objects.filter(pk=attempt.pk, status=Attempt.Status.IN_PROGRESS).update(
            status=status, submitted_at=timezone.now()
        )
        attempt.refresh_from_db()
        if changed:
            grade(attempt)
            attempt.refresh_from_db()
    return bool(changed)


def void_attempt(attempt: Attempt) -> bool:
    """Cancel an attempt (teacher action). Returns True if it changed.

    Only the status changes: answers and the score stay for the teacher, and everything that
    counts results (gradebook, profile, results, name-based attempt limits) already skips
    voided attempts."""
    if attempt.status == Attempt.Status.VOIDED:
        return False
    attempt.status = Attempt.Status.VOIDED
    attempt.save(update_fields=["status"])
    return True


def is_past_deadline(attempt: Attempt, grace: timedelta = timedelta(0)) -> bool:
    return bool(attempt.deadline_at and timezone.now() > attempt.deadline_at + grace)


def enforce_deadline(attempt: Attempt) -> bool:
    """Auto-submit an overdue attempt. Returns True when the attempt is finished."""
    if attempt.status == Attempt.Status.IN_PROGRESS and is_past_deadline(attempt):
        finalize(attempt, Attempt.Status.AUTO_SUBMITTED)
    return attempt.is_finished


EXTEND_CHOICES = (5, 10, 15)  # minutes a teacher can add in one step


def extend_time(sitting: Sitting, minutes: int) -> int:
    """Give every attempt that is still in progress ``minutes`` more. Returns how many.

    An attempt whose time ran out a moment ago but that is not submitted yet counts from now,
    so "5 more minutes" always means at least 5 minutes. Attempts without a time limit, and
    students who start later (they get the full time anyway), are not touched.
    """
    if minutes <= 0:
        return 0
    extra = timedelta(minutes=minutes)
    count = 0
    with transaction.atomic():
        attempts = sitting.attempts.select_for_update().filter(
            status=Attempt.Status.IN_PROGRESS, deadline_at__isnull=False
        )
        now = timezone.now()
        for attempt in attempts:
            attempt.deadline_at = max(attempt.deadline_at, now) + extra
            attempt.save(update_fields=["deadline_at"])
            count += 1
    return count


def close_sitting(sitting: Sitting) -> int:
    """Close a session and finalise all of its in-progress attempts. Returns how many."""
    if sitting.status != Sitting.Status.CLOSED:
        sitting.status = Sitting.Status.CLOSED
        sitting.closed_at = timezone.now()
        sitting.save(update_fields=["status", "closed_at"])
    count = 0
    for attempt in sitting.attempts.filter(status=Attempt.Status.IN_PROGRESS):
        if finalize(attempt, Attempt.Status.AUTO_SUBMITTED):
            count += 1
    return count


def reopen_sitting(sitting: Sitting) -> bool:
    """Let students join again with the same link and code. Returns False if already open.

    Attempts that were submitted automatically when the session closed stay as they are.
    """
    if sitting.status == Sitting.Status.OPEN:
        return False
    sitting.status = Sitting.Status.OPEN
    sitting.closed_at = None
    sitting.save(update_fields=["status", "closed_at"])
    return True


def delete_sitting(sitting: Sitting) -> int:
    """Delete a session with all its attempts and answers. Returns the number of attempts."""
    count = sitting.attempts.count()
    sitting.delete()
    return count


# --- linking attempts to students (KT-604) ----------------------------------------------------


class LinkError(ValueError):
    """A chosen student is not one the teacher may link to (stale page or tampering)."""


def apply_links(attempts, choices: dict[int, int | None], pool: dict[int, object]) -> int:
    """Set `Attempt.student` for many attempts at once, all or nothing.

    `choices` maps attempt pk -> student pk (None = unlink). `pool` maps student pk -> Student
    for the students the teacher may link to (the session owner's active students). An attempt
    that keeps the student it already has is always fine, even if that student is not in the
    pool any more. Attempts not in `attempts` are ignored. `Attempt.taker` is never touched.
    Returns the number of attempts changed."""
    by_pk = {a.pk: a for a in attempts}
    changes = []
    for attempt_pk, student_pk in choices.items():
        attempt = by_pk.get(attempt_pk)
        if attempt is None or student_pk == attempt.student_id:
            continue
        if student_pk is not None and student_pk not in pool:
            raise LinkError(student_pk)
        changes.append((attempt, student_pk))
    with transaction.atomic():
        for attempt, student_pk in changes:
            attempt.student = pool[student_pk] if student_pk is not None else None
            attempt.save(update_fields=["student"])
    return len(changes)


# --- teacher live stats ------------------------------------------------------------------------


def session_stats(sitting: Sitting) -> dict:
    from django.db.models import Count, Q

    test = sitting.revision.test
    fields = taker_fields(test)
    total = len(test.get("questions", []))
    attempts = (
        sitting.attempts.exclude(status=Attempt.Status.VOIDED)
        .select_related("student__group")
        .annotate(answered=Count("answers", filter=Q(answers__value__isnull=False)))
    )
    takers = []
    in_progress = submitted = linked = 0
    for attempt in attempts:
        if attempt.status == Attempt.Status.IN_PROGRESS:
            in_progress += 1
        else:
            submitted += 1
        takers.append(
            {
                "name": taker_display(attempt, fields),
                "status": attempt.status,
                "status_label": str(attempt.get_status_display()),
                "answered": attempt.answered,
                # the roster class of a linked student, shown next to the name
                "group": attempt.student.group.name
                if attempt.student_id and attempt.student.group_id
                else "",
            }
        )
        linked += 1 if attempt.student_id else 0
    return {
        "timed": time_limit_minutes(test) is not None,
        "joined": len(takers),
        "linked": linked,
        "in_progress": in_progress,
        "submitted": submitted,
        "total_questions": total,
        "status": sitting.status,
        "takers": takers,
    }
