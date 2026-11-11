"""Business logic for tests: projects, creating drafts, publishing revisions."""

from __future__ import annotations

from django.db import transaction
from django.utils.translation import gettext as _

from apps.exchange.importer import import_document
from apps.exchange.serializer import content_hash

from .models import Assessment, Project, Revision

DEFAULT_PROJECT_TITLE = "My tests"


def visible_projects(user):
    """Projects the user may see: their own, or all for admins."""
    qs = Project.objects.filter(is_archived=False)
    return qs if user.is_admin_role else qs.filter(owner=user)


def visible_assessments(user):
    qs = Assessment.objects.select_related("project", "project__owner")
    return qs if user.is_admin_role else qs.filter(project__owner=user)


def ensure_default_project(user) -> Project:
    """Make sure the user owns at least one project (auto-created "My tests")."""
    project = Project.objects.filter(owner=user, is_archived=False).first()
    if project is None:
        project = Project.objects.create(owner=user, title=_(DEFAULT_PROJECT_TITLE))
    return project


def create_assessment(project: Project, document: dict) -> Assessment:
    """Create a draft test from a normalised Test Document."""
    test = document["test"]
    return Assessment.objects.create(
        project=project,
        title=test["title"],
        description=test.get("description", ""),
        language=test.get("language", "en"),
        document=document,
    )


def publish(assessment: Assessment, user) -> tuple[Revision | None, str | None, bool]:
    """Publish the draft. Returns (revision, error_text, created).

    No new revision is created if the content equals the latest revision.
    """
    result = import_document(assessment.document)
    if not result.ok:
        return None, result.report.as_text(), False
    document = result.document
    digest = content_hash(document)
    with transaction.atomic():
        latest = assessment.revisions.order_by("-number").first()
        created = latest is None or latest.content_hash != digest
        if created:
            revision = Revision.objects.create(
                assessment=assessment,
                number=(latest.number + 1) if latest else 1,
                document=document,
                content_hash=digest,
                created_by=user,
            )
        else:
            revision = latest
        assessment.document = document
        assessment.status = Assessment.Status.PUBLISHED
        assessment.has_unpublished_changes = False
        assessment.save(
            update_fields=["document", "status", "has_unpublished_changes", "updated_at"]
        )
    return revision, None, created
