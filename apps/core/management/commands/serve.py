"""LAN mode: serve the app with Waitress, print URLs and a terminal QR (plan §12.2, §19)."""

import os
import subprocess
import sys
from datetime import timedelta
from pathlib import Path

from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.utils.translation import gettext as _

from apps.core import backup
from apps.core.datadir import sync_warning
from apps.core.lan import lan_ipv4_addresses

LAN_SETTINGS = "config.settings.lan"
BACKUP_FRESH = timedelta(minutes=10)
FIREWALL_COMMAND = (
    'New-NetFirewallRule -DisplayName "Knowledge Tester" -Direction Inbound '
    "-Protocol TCP -LocalPort {port} -Action Allow -Profile Private"
)


def static_root_is_empty(static_root: Path) -> bool:
    return not static_root.is_dir() or not any(static_root.iterdir())


class Command(BaseCommand):
    help = "Serve Knowledge Tester on the local network (Waitress, DEBUG off)."

    def add_arguments(self, parser):
        parser.add_argument("--host", default="0.0.0.0")
        parser.add_argument("--port", type=int, default=8000)
        parser.add_argument("--threads", type=int, default=8)
        parser.add_argument("--no-qr", action="store_true", help="Do not print the terminal QR.")
        parser.add_argument(
            "--open", action="store_true", help="Open the app in this computer's browser."
        )

    def handle(self, *args, **options):
        from django.conf import settings

        # LAN mode must run with DEBUG off. manage.py defaults to dev settings, so re-run
        # this command in a child process that uses config.settings.lan.
        if settings.SETTINGS_MODULE != LAN_SETTINGS:
            env = {**os.environ, "DJANGO_SETTINGS_MODULE": LAN_SETTINGS}
            try:
                code = subprocess.call([sys.executable, sys.argv[0], *sys.argv[1:]], env=env)
            except KeyboardInterrupt:
                code = 0
            sys.exit(code)

        host, port = options["host"], options["port"]
        data_dir = Path(settings.DATA_DIR)

        # Every start, not only the first: after an update the copies in the data folder would
        # otherwise stay old (collectstatic only rewrites files that changed).
        if static_root_is_empty(Path(settings.STATIC_ROOT)):
            self.stdout.write(_("Collecting static files..."))
        call_command("collectstatic", interactive=False, verbosity=0)

        self.stdout.write(self.style.SUCCESS("Knowledge Tester"))
        self.stdout.write(_("Data folder: %(path)s") % {"path": data_dir})
        warning = sync_warning(data_dir)
        if warning:
            self.stdout.write(self.style.WARNING(_("WARNING: %(text)s") % {"text": warning}))

        self._backup_at_start()

        urls = self._urls(host, port)
        self.stdout.write(_("Open on this computer or on phones in the same network:"))
        for url in urls:
            self.stdout.write(f"  {url}")
        if not options["no_qr"]:
            self._print_qr(urls[0])
        if os.name == "nt":
            self.stdout.write(
                "\n"
                + _("If phones cannot connect, run once as administrator (PowerShell):")
                + "\n  "
                + FIREWALL_COMMAND.format(port=port)
            )
        self.stdout.write("\n" + _("Press Ctrl+C to stop.") + "\n")
        self.stdout.flush()

        from waitress import serve

        from config.wsgi import application

        if options["open"]:
            # The teacher area: it leads to the first-run page, the login or the dashboard.
            self._open_browser(f"http://localhost:{port}/teach/")

        try:
            serve(application, host=host, port=port, threads=options["threads"], _quiet=True)
        except KeyboardInterrupt:
            self.stdout.write(_("Stopped."))

    def _backup_at_start(self) -> None:
        """One backup per start; a restart within a few minutes does not add another."""
        age = backup.newest_age()
        if age is not None and age < BACKUP_FRESH:
            return
        try:
            made = backup.create_backup("start")
        except backup.BackupError as error:
            self.stdout.write(self.style.WARNING(_("WARNING: %(text)s") % {"text": error}))
            return
        if made is not None:
            self.stdout.write(_("Backup: %(path)s") % {"path": made.path})

    @staticmethod
    def _open_browser(url: str) -> None:
        import threading
        import webbrowser

        # A moment later, when Waitress is listening.
        timer = threading.Timer(1.5, webbrowser.open, args=[url])
        timer.daemon = True
        timer.start()

    @staticmethod
    def _urls(host: str, port: int) -> list[str]:
        if host not in ("0.0.0.0", "::", ""):
            return [f"http://{host}:{port}"]
        addresses = lan_ipv4_addresses()
        return [f"http://{a}:{port}" for a in addresses] + [f"http://localhost:{port}"]

    def _print_qr(self, url: str) -> None:
        import segno

        self.stdout.write("\n" + _("Scan to open %(url)s") % {"url": url} + "\n")
        # Terminal output is block characters; make sure the console can encode them.
        try:
            segno.make(url, error="m").terminal(out=sys.stdout, compact=True)
        except UnicodeEncodeError:
            segno.make(url, error="m").terminal(out=sys.stdout)
