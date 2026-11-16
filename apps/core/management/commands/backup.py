"""Copy the database into <data folder>/backups/ (safe while the server is running)."""

from django.core.management.base import BaseCommand, CommandError

from apps.core import backup


class Command(BaseCommand):
    help = "Back up the database into the backups folder of the data folder."
    requires_system_checks = []  # must work before the first migrate

    def add_arguments(self, parser):
        parser.add_argument(
            "--reason",
            choices=["manual", "start"],
            default="manual",
            help="Recorded in the file name (the launcher uses 'start').",
        )
        parser.add_argument("--quiet", action="store_true", help="Print errors only.")

    def handle(self, *args, **options):
        try:
            made = backup.create_backup(options["reason"])
        except backup.BackupError as error:
            raise CommandError(str(error)) from error
        if options["quiet"]:
            return
        if made is None:
            self.stdout.write("No database yet, nothing to back up.")
            return
        self.stdout.write(self.style.SUCCESS(f"Backup written: {made.path}"))
