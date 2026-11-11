"""Glue between the pure grading engine and the delivery models."""

from __future__ import annotations

from django.db import transaction

from apps.delivery.models import Answer

from .engine import NEEDS_REVIEW, grade_answer, grade_test


@transaction.atomic
def grade_attempt(attempt) -> None:
    """(Re)grade an attempt and write the results to its Answer rows and its own totals.

    Idempotent. Creates missing Answer rows for unanswered questions. A set `manual_score`
    always wins over the automatic score.
    """
    test = attempt.sitting.revision.test
    grading_enabled = (test.get("grading") or {}).get("enabled", True)
    questions = {str(q["id"]): q for q in test.get("questions", [])}

    existing = {a.question_key: a for a in attempt.answers.all()}
    missing = [
        Answer(attempt=attempt, question_key=qid, status=Answer.Status.UNANSWERED)
        for qid in questions
        if qid not in existing
    ]
    if missing:
        Answer.objects.bulk_create(missing)
        existing.update({a.question_key: a for a in missing})

    values = {qid: existing[qid].value for qid in questions}
    manual = {
        qid: existing[qid].manual_score
        for qid in questions
        if existing[qid].manual_score is not None
    }
    result = grade_test(test, values, manual)

    changed = []
    for qid, question in questions.items():
        answer = existing[qid]
        auto = grade_answer(question, answer.value)
        if not grading_enabled:
            new_score, new_status = None, result.per_question[qid].status
        else:
            new_score = auto.points
            new_status = auto.status
            if auto.status == NEEDS_REVIEW and answer.manual_score is not None:
                new_status = Answer.Status.REVIEWED
        if answer.auto_score != new_score or answer.status != new_status:
            answer.auto_score = new_score
            answer.status = new_status
            changed.append(answer)
    if changed:
        Answer.objects.bulk_update(changed, ["auto_score", "status"])

    attempt.score = result.score
    attempt.max_score = result.max_score
    attempt.percent = result.percent
    attempt.grade = result.grade
    attempt.pending_reviews = result.pending_reviews
    attempt.save(update_fields=["score", "max_score", "percent", "grade", "pending_reviews"])
