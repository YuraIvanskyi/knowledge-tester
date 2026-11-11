import uuid

from django.conf import settings
from django.db import models

# Unambiguous alphabet (no 0/O, 1/I/L), plan §12.1
CODE_ALPHABET = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"
CODE_LENGTH = 6


class Sitting(models.Model):
    """A session: one opening of a published revision for takers."""

    class Status(models.TextChoices):
        OPEN = "open", "Open"
        CLOSED = "closed", "Closed"

    revision = models.ForeignKey(
        "assessments.Revision", on_delete=models.PROTECT, related_name="sittings"
    )
    code = models.CharField(max_length=CODE_LENGTH, unique=True)
    title = models.CharField(max_length=200, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.OPEN)
    access_code = models.CharField(max_length=32, blank=True)
    closes_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="sittings"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    closed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.code} ({self.title or self.revision})"


class Attempt(models.Model):
    class Status(models.TextChoices):
        IN_PROGRESS = "in_progress", "In progress"
        SUBMITTED = "submitted", "Submitted"
        AUTO_SUBMITTED = "auto_submitted", "Auto-submitted"
        VOIDED = "voided", "Voided"

    sitting = models.ForeignKey(Sitting, on_delete=models.CASCADE, related_name="attempts")
    token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    taker = models.JSONField(default=dict)  # taker field values, e.g. {"name": "..."}
    question_order = models.JSONField(default=list)  # list of question ids as shown
    option_orders = models.JSONField(default=dict)  # {question_id: [option ids]}
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.IN_PROGRESS)
    started_at = models.DateTimeField(auto_now_add=True)
    deadline_at = models.DateTimeField(null=True, blank=True)
    submitted_at = models.DateTimeField(null=True, blank=True)

    # Denormalized totals: only ever written by apps.grading.service
    score = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    max_score = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    percent = models.DecimalField(max_digits=5, decimal_places=1, null=True, blank=True)
    grade = models.CharField(max_length=32, blank=True)
    pending_reviews = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["started_at"]

    def __str__(self) -> str:
        return f"Attempt {str(self.token)[:4].upper()} ({self.taker.get('name', '?')})"

    @property
    def is_finished(self) -> bool:
        return self.status != self.Status.IN_PROGRESS


class Answer(models.Model):
    class Status(models.TextChoices):
        UNANSWERED = "unanswered", "Unanswered"
        GRADED = "graded", "Graded"
        NEEDS_REVIEW = "needs_review", "Needs review"
        REVIEWED = "reviewed", "Reviewed"

    attempt = models.ForeignKey(Attempt, on_delete=models.CASCADE, related_name="answers")
    question_key = models.CharField(max_length=64)
    # Choice types: list of option ids. short_answer / open: string.
    value = models.JSONField(null=True, blank=True)
    saved_at = models.DateTimeField(auto_now=True)
    auto_score = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    manual_score = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    status = models.CharField(max_length=14, choices=Status.choices, default=Status.UNANSWERED)
    feedback = models.TextField(blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["attempt", "question_key"], name="uniq_answer_per_q")
        ]

    def __str__(self) -> str:
        return f"{self.question_key}: {self.value!r}"

    @property
    def points(self):
        """Effective points: the reviewer's score wins over the automatic one."""
        return self.manual_score if self.manual_score is not None else self.auto_score
