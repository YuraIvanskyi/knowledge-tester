"""Data preparation for the results pages (no HTTP here)."""

from __future__ import annotations

import statistics
from collections import Counter
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

from django.utils.translation import gettext as _

from apps.delivery.models import Answer, Attempt
from apps.exchange import variants as test_variants

FINISHED = (Attempt.Status.SUBMITTED, Attempt.Status.AUTO_SUBMITTED)
CHOICE_TYPES = ("single_choice", "multiple_choice", "choose_n")
REVIEWABLE = (Answer.Status.NEEDS_REVIEW, Answer.Status.REVIEWED)

ZERO = Decimal("0.00")


def taker_name(attempt: Attempt) -> str:
    taker = attempt.taker or {}
    name = str(taker.get("name") or "").strip()
    if name:
        return name
    for value in taker.values():
        if str(value).strip():
            return str(value).strip()
    return _("(no name)")


def can_view_sitting(user, sitting) -> bool:
    """Only the teacher who created the session, or an admin, may see its results."""
    return user.is_authenticated and (user.is_admin_role or sitting.created_by_id == user.id)


def effective_points(answer: Answer | None) -> Decimal:
    if answer is None or answer.points is None:
        return ZERO
    return answer.points


def ordered_questions(test: dict, question_order: list | None) -> list[dict]:
    """Questions in the order the taker saw them; unknown ids dropped, missing ones appended."""
    by_id = {str(q["id"]): q for q in test.get("questions", [])}
    ordered = [by_id[str(i)] for i in (question_order or []) if str(i) in by_id]
    seen = {str(q["id"]) for q in ordered}
    ordered += [q for qid, q in by_id.items() if qid not in seen]
    return ordered


# ---- the attempt sheet ------------------------------------------------------------------


@dataclass
class SheetRow:
    number: int
    question: dict
    answer: Answer | None
    selected: list[str] = field(default_factory=list)  # option texts (choice types)
    text_answer: str = ""  # short_answer / open
    correct: list[str] = field(default_factory=list)  # option texts or accepted answers
    points: Decimal = ZERO
    max_points: Decimal = ZERO
    marker: str = "unanswered"  # correct | partial | wrong | pending | unanswered | ungraded
    marker_label: str = ""
    can_review: bool = False
    # Review form state: what the teacher typed (kept when the row was rejected) and why.
    form_points: str | None = None
    form_comment: str | None = None
    error: str = ""

    @property
    def blank(self) -> bool:
        return not self.selected and not self.text_answer.strip()

    @property
    def css_class(self) -> str:
        return MARKER_CLASSES[self.marker]


MARKER_CLASSES = {
    "correct": "status-ok",
    "partial": "status-warn",
    "wrong": "status-bad",
    "pending": "status-warn",
    "unanswered": "muted",
    "ungraded": "muted",
}


def marker_label(marker: str) -> str:
    return {
        "correct": _("Correct"),
        "partial": _("Partly correct"),
        "wrong": _("Wrong"),
        "pending": _("Needs review"),
        "unanswered": _("No answer"),
        "ungraded": _("Not graded"),
    }[marker]


def build_sheet(attempt: Attempt, test: dict, answers: list[Answer]) -> list[SheetRow]:
    by_key = {a.question_key: a for a in answers}
    grading_enabled = (test.get("grading") or {}).get("enabled", True)
    rows: list[SheetRow] = []
    for number, question in enumerate(ordered_questions(test, attempt.question_order), start=1):
        qid = str(question["id"])
        answer = by_key.get(qid)
        row = SheetRow(number=number, question=question, answer=answer)
        value = answer.value if answer else None
        if question["type"] in CHOICE_TYPES:
            chosen = {value} if isinstance(value, str) else set(value or [])
            options = question.get("options", [])
            row.selected = [str(o["text"]) for o in options if o["id"] in chosen]
            row.correct = [str(o["text"]) for o in options if o.get("correct")]
        else:
            row.text_answer = "" if value is None else str(value)
            if question["type"] == "short_answer":
                row.correct = [str(x) for x in question.get("accept", [])]
        row.max_points = Decimal(str(question.get("points", 1)))
        row.points = effective_points(answer)
        row.can_review = bool(
            grading_enabled
            and answer
            and answer.status in REVIEWABLE
            and attempt.status != Attempt.Status.VOIDED
        )

        status = answer.status if answer else Answer.Status.UNANSWERED
        if row.max_points == 0 or not grading_enabled:
            marker = "ungraded"
        elif status == Answer.Status.NEEDS_REVIEW:
            marker = "pending"
        elif row.blank and answer is not None and answer.manual_score is None:
            marker = "unanswered"
        elif row.points >= row.max_points:
            marker = "correct"
        elif row.points > 0:
            marker = "partial"
        else:
            marker = "wrong"
        row.marker = marker
        row.marker_label = marker_label(marker)
        rows.append(row)
    return rows


def next_unreviewed_attempt(attempt: Attempt) -> Attempt | None:
    """The next attempt of the same session that still has answers waiting for review."""
    pending = list(
        Attempt.objects.filter(
            sitting_id=attempt.sitting_id, pending_reviews__gt=0, status__in=FINISHED
        )
        .exclude(pk=attempt.pk)
        .order_by("started_at", "pk")
        .only("pk", "started_at")
    )
    if not pending:
        return None
    for other in pending:
        if (other.started_at, other.pk) > (attempt.started_at, attempt.pk):
            return other
    return pending[0]


# ---- session summary --------------------------------------------------------------------

SORTS = ("name", "-name", "score", "-score", "time", "-time")
STATUS_FILTERS = ("all", "finished", "in_progress", "needs_review", "voided")


def filter_and_sort(attempts: list[Attempt], status: str, sort: str) -> list[Attempt]:
    """A voided attempt shows only under the "voided" filter, never in the other lists."""
    if status != "voided":
        attempts = [a for a in attempts if a.status != Attempt.Status.VOIDED]
    if status == "finished":
        attempts = [a for a in attempts if a.status in FINISHED]
    elif status == "in_progress":
        attempts = [a for a in attempts if a.status == Attempt.Status.IN_PROGRESS]
    elif status == "voided":
        attempts = [a for a in attempts if a.status == Attempt.Status.VOIDED]
    elif status == "needs_review":
        attempts = [a for a in attempts if a.pending_reviews > 0]
    return sort_attempts(attempts, sort)


def sort_attempts(attempts: list[Attempt], sort: str) -> list[Attempt]:
    """The order of the results table (`sort` is one of SORTS)."""
    descending = sort.startswith("-")
    key = sort.lstrip("-")
    if key == "name":
        return sorted(attempts, key=lambda a: taker_name(a).casefold(), reverse=descending)
    if key == "score":
        scored = [a for a in attempts if a.score is not None]
        unscored = [a for a in attempts if a.score is None]
        scored.sort(key=lambda a: (a.score, a.pk), reverse=descending)
        return scored + unscored
    return sorted(attempts, key=lambda a: (a.started_at, a.pk), reverse=descending)


def results_query(status: str, sort: str) -> str:
    """The results table's filter and sort as a query string ("" for the defaults), so a sheet
    opened from the table can go back and step through the same list."""
    parts = []
    if status != "all":
        parts.append(f"status={status}")
    if sort != "time":
        parts.append(f"sort={sort}")
    return "?" + "&".join(parts) if parts else ""


def parse_results_query(query) -> tuple[str, str]:
    """(status, sort) from a GET QueryDict, unknown values replaced by the defaults."""
    status = query.get("status", "all")
    sort = query.get("sort", "time")
    return (
        status if status in STATUS_FILTERS else "all",
        sort if sort in SORTS else "time",
    )


@dataclass
class Neighbours:
    previous: Attempt | None
    next: Attempt | None
    position: int  # 1-based place of the attempt in the list
    total: int


def neighbours(attempt: Attempt, attempts: list[Attempt], status: str, sort: str) -> Neighbours:
    """The attempts before and after `attempt` in the results table with this filter and sort.

    An attempt the filter leaves out (reviewed a moment ago under "needs review", a cancelled
    one under "all") is placed where the sort would put it, so stepping on from it still
    follows the list the teacher came from."""
    shown = filter_and_sort(attempts, status, sort)
    if all(a.pk != attempt.pk for a in shown):
        shown = sort_attempts([*shown, attempt], sort)
    index = next(i for i, a in enumerate(shown) if a.pk == attempt.pk)
    return Neighbours(
        previous=shown[index - 1] if index > 0 else None,
        next=shown[index + 1] if index + 1 < len(shown) else None,
        position=index + 1,
        total=len(shown),
    )


@dataclass
class Summary:
    takers: int = 0
    average_percent: Decimal | None = None
    average_score: Decimal | None = None
    median_percent: Decimal | None = None
    max_score: Decimal | None = None
    pending_answers: int = 0
    pending_attempts: int = 0
    distribution: list[dict] = field(default_factory=list)
    distribution_max: int = 1


def summarize(attempts: list[Attempt]) -> Summary:
    finished = [a for a in attempts if a.status in FINISHED]
    scored = [a for a in finished if a.score is not None and a.percent is not None]
    summary = Summary(takers=len(finished))
    summary.pending_answers = sum(a.pending_reviews for a in finished)
    summary.pending_attempts = sum(1 for a in finished if a.pending_reviews)
    if scored:
        one = Decimal("0.1")
        summary.average_percent = (sum(a.percent for a in scored) / len(scored)).quantize(
            one, rounding=ROUND_HALF_UP
        )
        summary.average_score = (sum(a.score for a in scored) / len(scored)).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        summary.median_percent = Decimal(statistics.median(a.percent for a in scored)).quantize(
            one, rounding=ROUND_HALF_UP
        )
        summary.max_score = scored[0].max_score
    buckets = [0] * 10
    for a in scored:
        buckets[min(int(a.percent // 10), 9)] += 1
    for i, count in enumerate(buckets):
        low, high = i * 10, (i + 1) * 10 - 1 if i < 9 else 100
        summary.distribution.append({"label": f"{low}–{high} %", "count": count})
    summary.distribution_max = max(max(buckets), 1)
    return summary


def item_analysis_by_variant(test: dict, attempts: list[Attempt]) -> list[dict]:
    """Item analysis per variant: [{"label", "takers", "items"}]. A plain test gives one
    group with an empty label. Every variant is counted over its own takers only."""
    if not test_variants.has_variants(test):
        return [{"label": "", "takers": None, "items": item_analysis(test, attempts)}]
    groups = []
    for variant_id in test_variants.variant_ids(test):
        own = [a for a in attempts if a.variant == variant_id]
        groups.append(
            {
                "label": test_variants.label(test, variant_id),
                "takers": sum(1 for a in own if a.status in FINISHED),
                "items": item_analysis(test_variants.view(test, variant_id), own),
            }
        )
    return groups


def item_analysis(test: dict, attempts: list[Attempt]) -> list[dict]:
    """Percent correct per question over the finished attempts, plus the top wrong option.
    `test` has plain questions (one variant's view) and `attempts` are its takers."""
    finished_ids = [a.pk for a in attempts if a.status in FINISHED]
    answers = Answer.objects.filter(attempt_id__in=finished_ids)
    total = len(finished_ids)
    earned: dict[str, Decimal] = {}
    wrong: dict[str, Counter] = {}
    answered: Counter = Counter()
    questions = {str(q["id"]): q for q in test.get("questions", [])}
    for answer in answers:
        question = questions.get(answer.question_key)
        if question is None:
            continue
        max_points = Decimal(str(question.get("points", 1)))
        points = min(max(effective_points(answer), ZERO), max_points)
        earned[answer.question_key] = earned.get(answer.question_key, ZERO) + points
        if answer.status != Answer.Status.UNANSWERED:
            answered[answer.question_key] += 1
        if question["type"] in CHOICE_TYPES:
            correct_ids = {o["id"] for o in question.get("options", []) if o.get("correct")}
            chosen = {answer.value} if isinstance(answer.value, str) else set(answer.value or [])
            wrong.setdefault(answer.question_key, Counter()).update(chosen - correct_ids)

    rows = []
    for number, (qid, question) in enumerate(questions.items(), start=1):
        max_points = Decimal(str(question.get("points", 1)))
        row = {
            "number": number,
            "id": qid,
            "text": question.get("text", ""),
            "answered": answered[qid],
            "percent": None,
            "top_wrong": None,
        }
        if max_points > 0 and total:
            row["percent"] = (earned.get(qid, ZERO) / (max_points * total) * 100).quantize(
                Decimal("0.1"), rounding=ROUND_HALF_UP
            )
        counter = wrong.get(qid)
        if counter:
            option_id, count = counter.most_common(1)[0]
            texts = {o["id"]: o["text"] for o in question.get("options", [])}
            row["top_wrong"] = {"text": texts.get(option_id, option_id), "count": count}
        rows.append(row)
    return rows
