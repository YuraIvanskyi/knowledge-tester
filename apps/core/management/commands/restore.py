"""Replace the database with a backup. Stop the server first."""

from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from apps.core import backup


class Command(BaseCommand):
    help = (
        "Restore the database from a backup file (a name from the backups folder, or a path). "
        "Stop the server first. The current database is backed up before it is replaced."
    )
    requires_system_checks = []

    def add_arguments(self, parser):
        parser.add_argument("file", nargs="?", help="Backup file name or path.")
        parser.add_argument("--list", action="store_true", help="List the available backups.")
        parser.add_argument("--yes", action="store_true", help="Do not ask for confirmation.")

    def handle(self, *args, **options):
        if options["list"] or not options["file"]:
            backups = backup.list_backups()
            if not backups:
                self.stdout.write(f"No backups in {backup.backup_dir()}")
            for item in backups:
                size = f"{item.size / 1024:.0f} KB"
                self.stdout.write(f"{item.name}  {item.created:%Y-%m-%d %H:%M}  {size}")
            if not options["list"]:
                raise CommandError("Say which backup to restore: manage.py restore <file name>")
            return

        source = Path(options["file"])
        if not source.is_file():
            found = backup.find_backup(options["file"])
            if found is None:
                raise CommandError(f"No such backup: {options['file']} (see restore --list)")
            source = found.path

        if not options["yes"]:
            self.stdout.write(
                f"The database {backup.database_path()} will be replaced with {source.name}.\n"
                "The server must be stopped. The current database is backed up first."
            )
            if input("Type yes to continue: ").strip().lower() != "yes":
                raise CommandError("Cancelled, nothing changed.")
        try:
            safety = backup.restore_backup(source)
        except backup.BackupError as error:
            raise CommandError(str(error)) from error
        self.stdout.write(self.style.SUCCESS(f"Restored from {source.name}."))
        if safety is not None:
            self.stdout.write(f"The previous database was saved as {safety.name}.")
        self.stdout.write("Now run: manage.py migrate, then start the server.")
