"""Base settings. Data lives outside the repo (plan §7, §19.3)."""

import os
import secrets
import tomllib
from pathlib import Path

from django.utils.csp import CSP

BASE_DIR = Path(__file__).resolve().parent.parent.parent


def _resolve_data_dir() -> Path:
    env = os.environ.get("KT_DATA_DIR")
    if env:
        path = Path(env)
    elif os.name == "nt":
        path = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "KnowledgeTester"
    else:
        path = Path.home() / ".local" / "share" / "knowledge-tester"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _load_config(data_dir: Path) -> dict:
    """Read kt.toml; generate and persist a SECRET_KEY on first run."""
    path = data_dir / "kt.toml"
    config = tomllib.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    if "secret_key" not in config:
        config["secret_key"] = secrets.token_urlsafe(50)
        with path.open("a", encoding="utf-8", newline="\n") as fh:
            fh.write(f'secret_key = "{config["secret_key"]}"\n')
    return config


DATA_DIR = _resolve_data_dir()
KT_CONFIG = _load_config(DATA_DIR)

SECRET_KEY = os.environ.get("KT_SECRET_KEY") or KT_CONFIG["secret_key"]
DEBUG = False
ALLOWED_HOSTS: list[str] = ["*"]  # prototype; computed from LAN IPs later (KT-005)

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "whitenoise.runserver_nostatic",
    "django.contrib.staticfiles",
    "apps.core",
    "apps.accounts",
    "apps.assessments",
    "apps.exchange",
    "apps.delivery",
    "apps.grading",
    "apps.reports",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.middleware.csp.ContentSecurityPolicyMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "apps.core.middleware.DefaultLanguageMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

# Offline by construction: nothing may be loaded from another origin (plan §5.2).
SECURE_CSP = {"default-src": [CSP.SELF]}

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
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

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": DATA_DIR / "db.sqlite3",
        "OPTIONS": {
            "transaction_mode": "IMMEDIATE",
            "timeout": 5,
            "init_command": (
                "PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL; PRAGMA busy_timeout=5000;"
            ),
        },
    }
}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

AUTH_USER_MODEL = "accounts.User"
LOGIN_URL = "accounts:login"
LOGIN_REDIRECT_URL = "core:dashboard"
LOGOUT_REDIRECT_URL = "core:landing"

# Ukrainian is the default UI language; users switch via the footer buttons (cookie).
LANGUAGE_CODE = "uk"
LANGUAGES = [("en", "English"), ("uk", "Українська")]
LOCALE_PATHS = [BASE_DIR / "locale"]
LANGUAGE_COOKIE_AGE = 60 * 60 * 24 * 365
LANGUAGE_COOKIE_SAMESITE = "Lax"
USE_I18N = True
USE_TZ = True
TIME_ZONE = "UTC"

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = DATA_DIR / "staticfiles"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedStaticFilesStorage"},
}
MEDIA_URL = "media/"
MEDIA_ROOT = DATA_DIR / "media"

SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
