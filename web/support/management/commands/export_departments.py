from pathlib import Path

from django.core.management.base import BaseCommand

from support.services import export_departments


class Command(BaseCommand):
    help = (
        "Write the active departments, routing settings and current load as a departments "
        "YAML file (for the CLI, the evaluation or another installation)."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument("path", type=Path, nargs="?", help="output file; default: stdout")

    def handle(self, *args, path: Path | None, **options) -> None:
        text = export_departments()
        if path is None:
            self.stdout.write(text, ending="")
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        self.stdout.write(self.style.SUCCESS(f"saved to {path}"))
