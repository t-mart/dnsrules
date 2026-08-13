"""Put the systemd units, and their sysusers and tmpfiles entries, into /etc.

The files are real files, shipped in the package under `units/`. That tree
mirrors `/etc`, so this command only copies. Nothing here writes a unit from a
template, because nothing in a unit depends on runtime state.

Every path inside a unit is fixed by convention. To change one on a router,
write a drop-in with `systemctl edit`, which survives the next upgrade.
"""

import shutil
from argparse import ArgumentParser
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

SOURCE = Path(settings.PACKAGE_DIR, "units")

AFTER = """
Then load them:

    systemd-sysusers
    systemd-tmpfiles --create
    systemctl daemon-reload
"""


def files() -> list[Path]:
    """Every shipped file, as a path relative to the tree root."""
    return sorted(
        path.relative_to(SOURCE) for path in SOURCE.rglob("*") if path.is_file()
    )


class Command(BaseCommand):
    help = "Copy the systemd units into /etc, or list where they go."

    def add_arguments(self, parser: ArgumentParser) -> None:
        parser.add_argument(
            "--output",
            type=Path,
            help="Copy the files under this directory. Without it, list them.",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Replace a file that is there already.",
        )

    def handle(self, *args, **options) -> None:
        root = options["output"]
        if root is None:
            for name in files():
                self.stdout.write(str(Path("/etc", name)))
            self.stdout.write("Copy them with --output /etc.")
            return

        # Check every target first. A half-copied unit set is worse than none,
        # because systemd starts what it has.
        targets = [(Path(SOURCE, name), Path(root, name)) for name in files()]
        if not options["force"]:
            clash = [target for _, target in targets if target.exists()]
            if clash:
                raise CommandError(
                    f"{len(clash)} files are there already, the first is {clash[0]}. "
                    f"Pass --force to replace them."
                )

        for source, target in targets:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
            target.chmod(0o644)
            self.stdout.write(str(target))
        self.stdout.write(AFTER)
