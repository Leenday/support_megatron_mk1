"""Django settings. Values come from `megatron.settings.Settings` (.env), like the CLI's."""

from pathlib import Path

import dj_database_url

from megatron.settings import Settings

BASE_DIR = Path(__file__).resolve().parent.parent
ENV = Settings()

DEBUG = ENV.django_debug
# Without a key only DEBUG may run: the system check support.E001 stops runserver and
# migrate otherwise (a check rather than an error here, so the tests need no key).
DEVELOPMENT_KEY = "django-insecure-development-only"
SECRET_KEY = ENV.django_secret_key.get_secret_value() if ENV.django_secret_key else DEVELOPMENT_KEY
ALLOWED_HOSTS = ENV.django_allowed_hosts

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "support",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "megatron_web.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "megatron_web.wsgi.application"

DATABASES = {
    "default": dj_database_url.parse(ENV.database_url, conn_max_age=600)
    if ENV.database_url
    else {"ENGINE": "django.db.backends.sqlite3", "NAME": BASE_DIR / "db.sqlite3"}
}

# Swapping the user model later is not supported by Django, so it is custom from the start.
AUTH_USER_MODEL = "support.User"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "ru"
TIME_ZONE = "Europe/Moscow"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "loggers": {"megatron": {"handlers": ["console"], "level": "INFO"}},
}
