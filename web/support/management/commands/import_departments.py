from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from pydantic import ValidationError

from support.models import Department
from support.services import import_departments_file


class Command(BaseCommand):
    help = (
        "Create or update departments and routing settings from a departments YAML file "
        "(matched by id; departments missing from the file are deactivated, never deleted)."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument("path", type=Path, help="e.g. config/departments.yaml")
        parser.add_argument(
            "--if-empty",
            action="store_true",
            help="only when there are no departments yet (first start of the service)",
        )

    def handle(self, *args, path: Path, if_empty: bool, **options) -> None:
        if if_empty and Department.objects.exists():
            self.stdout.write("departments already exist, nothing imported")
            return
        try:
            counts = import_departments_file(path)
        except (OSError, ValidationError) as e:
            raise CommandError(f"{path}: {e}") from e
        self.stdout.write(
            self.style.SUCCESS(
                f"{path}: {counts['created']} created, {counts['updated']} updated, "
                f"{counts['deactivated']} deactivated"
            )
        )
