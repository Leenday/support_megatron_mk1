from django.conf import settings
from django.core.checks import CheckMessage, Error, register


@register()
def secret_key_check(app_configs, **kwargs) -> list[CheckMessage]:
    if settings.DEBUG or settings.SECRET_KEY != settings.DEVELOPMENT_KEY:
        return []
    return [
        Error(
            "DJANGO_SECRET_KEY is not set",
            hint="Set it in .env, or DJANGO_DEBUG=true for development.",
            id="support.E001",
        )
    ]
