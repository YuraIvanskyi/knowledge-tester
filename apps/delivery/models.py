import uuid

from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.exchange import variants as test_variants

# Unambiguous alphabet (no 0/O, 1/I/L), plan §12.1
CODE_ALPHABET = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"
CODE_LENGTH = 6


class Sitting(models.Model):
    """A session: one opening of a published revision for takers."""

    class Status(models.TextChoices):
        OPEN = "open", _("Open")
        CLOSED = "closed", _("Closed")

    revision = models.ForeignKey(
        "assessments.Revision", on_delete=models.PROTECT, related_name="sittings"
    )
    code = models.CharField(max_length=CODE_LENGTH, unique=True)
    title = models.CharField(max_length=200, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.OPEN)
    access_code = models.CharField(max_length=32, blank=True)
    # Group-bound session (plan §14): takers pick their name from this group's roster.
    group = models.ForeignKey(
        "people.Group", null=True, blank=True, on_delete=models.SET_NULL, related_name="sittings"
    )
    # Group-bound only: the taker must also type their personal PIN (Student.pin).
    use_pin = models.BooleanField(default=False)
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
        IN_PROGRESS = "in_progress", _("In progress")
        SUBMITTED = "submitted", _("Submitted")
        AUTO_SUBMITTED = "auto_submitted", _("Auto-submitted")
        VOIDED = "voided", _("Voided")

    sitting = models.ForeignKey(Sitting, on_delete=models.CASCADE, related_name="attempts")
    token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    # Set automatically in group-bound sessions, or by the teacher afterwards (plan §14).
    # Deleting a student either unlinks (SET_NULL) or deletes the attempts: the service decides.
    student = models.ForeignKey(
        "people.Student", null=True, blank=True, on_delete=models.SET_NULL, related_name="attempts"
    )
    taker = models.JSONField(default=dict)  # taker field values, e.g. {"name": "..."}
    # Id of the variant this taker got; empty when the test has no variants.
    variant = models.CharField(max_length=40, blank=True)
    question_order = models.JSONField(default=list)  # list of question ids as shown
    option_orders = models.JSONField(default=dict)  # {question_id: [option ids]}
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.IN_PROGRESS)
    started_at = models.DateTimeField(auto_now_add=True)
    deadline_at = models.DateTimeField(null=True, blank=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    # How often and how long the taker left the test page (another tab or app), as reported by
    # the page (static/js/away.js). Only ever written by services.record_away.
    away_count = models.PositiveIntegerField(default=0)
    away_seconds = models.PositiveIntegerField(default=0)
    # Extra points the teacher gives the whole work (negative = a deduction), with the reason.
    # Counted by apps.grading.service.grade_attempt; the total never leaves 0..max_score.
    bonus_points = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    bonus_note = models.CharField(max_length=500, blank=True)

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

    @property
    def test(self) -> dict:
        """The test as this taker got it: plain ``questions`` (those of the attempt's variant).
        Everything that reads, grades or prints one attempt uses this, never the revision's
        test directly."""
        return test_variants.view(self.sitting.revision.test, self.variant)

    @property
    def variant_label(self) -> str:
        """ "Variant 2" (or the variant's own title); empty when the test has no variants."""
        return test_variants.label(self.sitting.revision.test, self.variant)


class Answer(models.Model):
    class Status(models.TextChoices):
        UNANSWERED = "unanswered", _("Unanswered")
        GRADED = "graded", _("Graded")
        NEEDS_REVIEW = "needs_review", _("Needs review")
        REVIEWED = "reviewed", _("Reviewed")

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
