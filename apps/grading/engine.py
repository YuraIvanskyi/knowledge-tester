"""Grading engine. Pure Python (no Django imports). Rules: plan §9.2 and common rules."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from fractions import Fraction

from .normalize import normalize_text, parse_number
from .scales import grade_label

ZERO = Decimal("0.00")

GRADED = "graded"
NEEDS_REVIEW = "needs_review"
UNANSWERED = "unanswered"

CHOICE_TYPES = ("single_choice", "multiple_choice", "choose_n")


@dataclass(frozen=True)
class AnswerResult:
    points: Decimal
    max_points: Decimal
    status: str  # "graded" | "needs_review" | "unanswered"


@dataclass(frozen=True)
class TestResult:
    __test__ = False  # not a pytest test class

    score: Decimal | None
    max_score: Decimal | None
    percent: Decimal | None
    grade: str
    pending_reviews: int
    per_question: dict[str, AnswerResult] = field(default_factory=dict)
    # The automatic result of each question before a reviewer's score is applied (only when
    # grading is enabled). Lets callers store auto and manual scores without grading twice.
    auto: dict[str, AnswerResult] = field(default_factory=dict)

    @property
    def provisional(self) -> bool:
        return self.pending_reviews > 0


def q2(value: Decimal | Fraction | int | str) -> Decimal:
    """Round to 2 places, half up."""
    if isinstance(value, Fraction):
        value = Decimal(value.numerator) / Decimal(value.denominator)
    return Decimal(value).quantize(ZERO, rounding=ROUND_HALF_UP)


def _points_of(question: dict) -> Decimal:
    raw = question.get("points", 1)
    try:
        points = Decimal(str(raw))
    except Exception as exc:
        raise ValueError(f"question {question.get('id')!r}: bad points {raw!r}") from exc
    if not points.is_finite() or points < 0:
        raise ValueError(f"question {question.get('id')!r}: bad points {raw!r}")
    return q2(points)


def _is_blank_text(value: object) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, list | tuple | set | frozenset):
        return len(value) == 0
    return False


def _selected_ids(question: dict, value: object) -> set[str]:
    """Selected option ids, restricted to the question's real options."""
    if value is None:
        return set()
    if isinstance(value, str):
        value = [value]
    try:
        chosen = {str(v) for v in value}  # type: ignore[union-attr]
    except TypeError:
        return set()
    return chosen & {str(o["id"]) for o in question.get("options", [])}


def _is_blank(question: dict, value: object) -> bool:
    if question.get("type") in CHOICE_TYPES:
        return not _selected_ids(question, value)
    return _is_blank_text(value)


def _grade_choice(question: dict, chosen: set[str], points: Decimal) -> Decimal:
    options = question.get("options", [])
    correct = {str(o["id"]) for o in options if o.get("correct")}
    incorrect = {str(o["id"]) for o in options} - correct
    right = chosen & correct
    wrong = chosen & incorrect
    qtype = question["type"]

    if qtype == "single_choice":
        if chosen == correct and len(correct) == 1:
            return points
        penalty = Decimal(str(question.get("penalty", 0) or 0))
        penalty = min(max(penalty, Decimal(0)), Decimal(1))
        return q2(-penalty * points)

    if qtype == "multiple_choice":
        mode = question.get("scoring") or "partial"
        if mode == "all_or_nothing":
            return points if correct and chosen == correct else ZERO
        if mode == "per_option":
            weights = {str(o["id"]): Decimal(str(o.get("weight", 0) or 0)) for o in options}
            total = sum((weights[i] for i in chosen), Decimal(0))
            return q2(min(max(total, Decimal(0)), points))
        # partial: P * max(0, |R|/|C| - |W|/|I|)
        if not correct:
            return ZERO
        ratio = Fraction(len(right), len(correct))
        if incorrect:
            ratio -= Fraction(len(wrong), len(incorrect))
        return q2(Fraction(points) * max(Fraction(0), ratio))

    # choose_n: P * |R| / n
    n = int(question.get("n") or len(correct))
    if n < 1:
        return ZERO
    return q2(Fraction(points) * Fraction(len(right), n))


def _short_answer_matches(question: dict, value: object) -> bool:
    accept = question.get("accept") or []
    if question.get("mode") == "numeric":
        given = parse_number(value)
        if given is None:
            return False
        tolerance = abs(parse_number(question.get("tolerance") or 0) or Decimal(0))
        for item in accept:
            wanted = parse_number(item)
            if wanted is not None and abs(given - wanted) <= tolerance:
                return True
        return False
    case_sensitive = bool(question.get("case_sensitive"))
    lookalike = bool(question.get("lookalike"))
    given_text = normalize_text(value, case_sensitive=case_sensitive, lookalike=lookalike)
    return any(
        given_text == normalize_text(item, case_sensitive=case_sensitive, lookalike=lookalike)
        for item in accept
    )


def grade_answer(question: dict, value: object) -> AnswerResult:
    """Grade one answer automatically. `open` (and unmatched reviewable) answers need review."""
    points = _points_of(question)
    qtype = question.get("type")
    if qtype not in (*CHOICE_TYPES, "short_answer", "open"):
        raise ValueError(f"question {question.get('id')!r}: unknown type {qtype!r}")

    blank = _is_blank(question, value)
    if points == 0:  # ungraded: nothing to score, nothing to review
        return AnswerResult(ZERO, ZERO, UNANSWERED if blank else GRADED)
    if blank:
        return AnswerResult(ZERO, points, UNANSWERED)

    if qtype in CHOICE_TYPES:
        return AnswerResult(
            _grade_choice(question, _selected_ids(question, value), points), points, GRADED
        )
    if qtype == "short_answer":
        if _short_answer_matches(question, value):
            return AnswerResult(points, points, GRADED)
        if question.get("review_unmatched"):
            return AnswerResult(ZERO, points, NEEDS_REVIEW)
        return AnswerResult(ZERO, points, GRADED)
    return AnswerResult(ZERO, points, NEEDS_REVIEW)  # open


def apply_manual(result: AnswerResult, manual: Decimal | int | str | None) -> AnswerResult:
    """A reviewer's score wins over the automatic one (clamped to 0..max)."""
    if manual is None or result.max_points == 0:
        return result
    score = min(max(q2(Decimal(str(manual))), ZERO), result.max_points)
    return AnswerResult(score, result.max_points, GRADED)


def grade_test(
    test: dict,
    answers: dict[str, object],
    manual_scores: dict[str, Decimal] | None = None,
    bonus: Decimal | int | str = ZERO,
) -> TestResult:
    """Grade a whole attempt. `answers` maps question id -> value.

    `bonus` is the teacher's extra points for the whole work (negative = a deduction). It is
    added to the sum of the questions and the total is kept within 0 .. max_score, so the
    percentage and the grade never go past the scale."""
    manual_scores = manual_scores or {}
    grading = test.get("grading") or {}
    enabled = grading.get("enabled", True)

    per_question: dict[str, AnswerResult] = {}
    auto: dict[str, AnswerResult] = {}
    for question in test.get("questions", []):
        qid = str(question["id"])
        value = answers.get(qid)
        if not enabled:
            status = UNANSWERED if _is_blank(question, value) else GRADED
            per_question[qid] = AnswerResult(ZERO, ZERO, status)
            continue
        result = auto[qid] = grade_answer(question, value)
        per_question[qid] = apply_manual(result, manual_scores.get(qid))

    if not enabled:
        return TestResult(None, None, None, "", 0, per_question)

    max_score = sum((r.max_points for r in per_question.values()), ZERO)
    score = sum((r.points for r in per_question.values()), ZERO) + Decimal(str(bonus or 0))
    score = min(max(score, ZERO), max(max_score, ZERO))
    pending = sum(1 for r in per_question.values() if r.status == NEEDS_REVIEW)
    percent = None
    if max_score > 0:
        percent = (score / max_score * 100).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
    grade = grade_label(grading, score, max_score, percent)
    return TestResult(q2(score), q2(max_score), percent, grade, pending, per_question, auto)
