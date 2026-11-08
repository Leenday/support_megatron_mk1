from django.apps import AppConfig


class SupportConfig(AppConfig):
    name = "support"
    verbose_name = "Support"

    def ready(self) -> None:
        from support import checks  # noqa: F401  (registers the system checks)
