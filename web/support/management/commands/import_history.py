from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from megatron.inputs import RequestFileError
from support.services import import_history


class Command(BaseCommand):
    help = (
        "Import solved tickets with a confirmed department (.jsonl with text and expected, the "
        "department id) as the history the classifier learns from (#73)."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument("path", type=Path, help="e.g. data/local/en/pool.jsonl")
        parser.add_argument(
            "--replace", action="store_true", help="delete the imported history first"
        )

    def handle(self, *args, path: Path, replace: bool, **options) -> None:
        try:
            count = import_history(path, replace=replace)
        except (OSError, RequestFileError, ValueError) as e:
            raise CommandError(f"{path}: {e}") from e
        self.stdout.write(self.style.SUCCESS(f"{path}: {count} history tickets imported"))
