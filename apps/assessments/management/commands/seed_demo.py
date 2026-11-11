"""Dev convenience: demo users and published sample tests. Do not use in production."""

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from apps.assessments import services
from apps.assessments.models import Assessment
from apps.exchange.importer import import_document

EXAMPLES = settings.BASE_DIR / "docs" / "examples"
ENGLISH_EXAMPLE = EXAMPLES / "full.json"
# Ukrainian demo tests: one file per subject, together they use every question type.
UKRAINIAN_EXAMPLES = sorted((EXAMPLES / "ua").glob("*.json"))
DEMO_FILES = [ENGLISH_EXAMPLE, *UKRAINIAN_EXAMPLES]


class Command(BaseCommand):
    help = (
        "Create demo users (teacher/teacher, admin/admin) and publish the demo tests: "
        "four Ukrainian ones (docs/examples/ua) and the English docs/examples/full.json."
    )

    def handle(self, *args, **options):
        User = get_user_model()

        teacher, created = User.objects.get_or_create(
            username="teacher", defaults={"role": "teacher", "display_name": "Демо-вчитель"}
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

        project = services.ensure_default_project(teacher)
        for path in DEMO_FILES:
            self._load(path, project, teacher)

    def _load(self, path, project, teacher):
        result = import_document(path.read_bytes())
        if not result.ok:
            raise CommandError(f"The demo test {path.name} is invalid:\n" + result.report.as_text())

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
