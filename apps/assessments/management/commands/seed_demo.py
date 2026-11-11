"""Dev convenience: demo users and a published sample test. Do not use in production."""

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from apps.assessments import services
from apps.assessments.models import Assessment
from apps.exchange.importer import import_document

EXAMPLE = settings.BASE_DIR / "docs" / "examples" / "full.json"


class Command(BaseCommand):
    help = "Create demo users (teacher/teacher, admin/admin) and a published sample test."

    def handle(self, *args, **options):
        User = get_user_model()

        teacher, created = User.objects.get_or_create(
            username="teacher", defaults={"role": "teacher", "display_name": "Demo Teacher"}
        )
        if created:
            teacher.set_password("teacher")
            teacher.save()
        self.stdout.write(f"teacher: {'created' if created else 'exists'} (password: teacher)")

        admin, created = User.objects.get_or_create(
            username="admin", defaults={"is_staff": True, "is_superuser": True}
        )
        if created:
            admin.set_password("admin")
            admin.save()
        self.stdout.write(f"admin: {'created' if created else 'exists'} (password: admin)")

        result = import_document(EXAMPLE.read_bytes())
        if not result.ok:
            raise CommandError("The sample test is invalid:\n" + result.report.as_text())

        project = services.ensure_default_project(teacher)
        title = result.document["test"]["title"]
        assessment = Assessment.objects.filter(project__owner=teacher, title=title).first()
        if assessment is None:
            assessment = services.create_assessment(project, result.document)
            self.stdout.write(f'Imported test "{title}" (#{assessment.pk}).')
        else:
            self.stdout.write(f'Test "{title}" already exists (#{assessment.pk}).')

        revision, error, created = services.publish(assessment, teacher)
        if error:
            raise CommandError(error)
        verb = "Published" if created else "Already published as"
        self.stdout.write(self.style.SUCCESS(f"{verb} revision {revision.number}."))
