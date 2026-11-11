"""Prototype data model.

Deviation from plan §8 (see idea/log.md): questions and options are NOT separate tables yet.
The authoritative content of a test is its Test Document (plan §11) stored as JSON, both for the
editable draft (`Assessment.document`) and for published snapshots (`Revision.document`).
Every question and option in a stored document has an `id` (assigned by the importer).
"""

from django.conf import settings
from django.db import models


class Project(models.Model):
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="projects"
    )
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    is_archived = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["title"]

    def __str__(self) -> str:
        return self.title


class Assessment(models.Model):
    """A test ("Test" in the UI)."""

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        PUBLISHED = "published", "Published"
        ARCHIVED = "archived", "Archived"

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="assessments")
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    language = models.CharField(max_length=8, default="en")
    # Full Test Document (format/version/test), see plan §11.
    document = models.JSONField(default=dict)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.DRAFT)
    has_unpublished_changes = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]

    def __str__(self) -> str:
        return self.title

    @property
    def owner(self):
        return self.project.owner


class Revision(models.Model):
    """Immutable snapshot of a test, created on publish."""

    assessment = models.ForeignKey(Assessment, on_delete=models.CASCADE, related_name="revisions")
    number = models.PositiveIntegerField()
    document = models.JSONField()
    content_hash = models.CharField(max_length=64)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-number"]
        constraints = [
            models.UniqueConstraint(fields=["assessment", "number"], name="uniq_revision_number")
        ]

    def __str__(self) -> str:
        return f"{self.assessment.title} rev. {self.number}"

    @property
    def test(self) -> dict:
        """The inner `test` object of the Test Document."""
        return self.document["test"]
