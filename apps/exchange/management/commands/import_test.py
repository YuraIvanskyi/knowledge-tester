"""Import a Test Document file as a draft test: import_test FILE --project TITLE --user USERNAME."""

from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from apps.assessments.models import Project
from apps.assessments.services import create_assessment
from apps.exchange.importer import import_document


class Command(BaseCommand):
    help = "Import a test JSON file as a draft test for a user."

    def add_arguments(self, parser):
        parser.add_argument("file", type=Path)
        parser.add_argument("--project", required=True, help="Project title (created if missing).")
        parser.add_argument("--user", required=True, help="Username of the owner.")

    def handle(self, *args, file, project, user, **options):
        try:
            owner = get_user_model().objects.get(username=user)
        except get_user_model().DoesNotExist:
            raise CommandError(f'No such user: "{user}".') from None
        try:
            data = file.read_bytes()
        except OSError as exc:
            raise CommandError(f"Cannot read {file}: {exc}") from None

        result = import_document(data)
        for line in result.report.as_text().splitlines():
            self.stdout.write(line)
        if not result.ok:
            raise CommandError("Import failed, nothing was created.")

        proj, _ = Project.objects.get_or_create(owner=owner, title=project)
        assessment = create_assessment(proj, result.document)
        self.stdout.write(
            self.style.SUCCESS(
                f'Created test #{assessment.pk} "{assessment.title}" in project "{proj.title}".'
            )
        )
