import os
from pathlib import Path

import dj_database_url
import environ


BASE_DIR = Path(__file__).resolve().parent.parent

env = environ.Env(
    DEBUG=(bool, False),
    ALLOWED_HOSTS=(list, ["127.0.0.1", "localhost"]),
    CSRF_TRUSTED_ORIGINS=(list, []),
    MAX_UPLOAD_SIZE_MB=(int, 10),
    MAX_VOICE_MESSAGE_SIZE_MB=(int, 20),
    VOICE_AUTOCONFIRM_SECONDS=(int, 3),
    PROCESS_MINING_TIMEOUT_SECONDS=(int, 10),
    PROCESS_MINING_BATCH_SIZE=(int, 100),
    PROCESS_MINING_EXPORT_INTERVAL_SECONDS=(int, 5),
    PROCESS_MINING_MAX_RETRIES=(int, 5),
    PROCESS_MINING_CONNECT_TIMEOUT=(int, 3),
    PROCESS_MINING_READ_TIMEOUT=(int, 15),
)
environ.Env.read_env(BASE_DIR / ".env", overwrite=True)

SECRET_KEY = env("SECRET_KEY", default="dev-only-change-me")
DEBUG = env("DEBUG")
ALLOWED_HOSTS = env("ALLOWED_HOSTS")
RENDER_EXTERNAL_HOSTNAME = os.environ.get("RENDER_EXTERNAL_HOSTNAME")
if RENDER_EXTERNAL_HOSTNAME and RENDER_EXTERNAL_HOSTNAME not in ALLOWED_HOSTS:
    ALLOWED_HOSTS.append(RENDER_EXTERNAL_HOSTNAME)

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "django_filters",
    "drf_spectacular",
    "apps.accounts",
    "apps.audit",
    "apps.notifications",
    "apps.quality",
    "apps.bakery",
    "apps.process_mining",
    "apps.equipment",
    "apps.inspections",
    "apps.nonconformities",
    "apps.dashboard",
    "apps.reports",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "apps.audit.middleware.CurrentRequestMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "apps.notifications.context_processors.unread_notifications",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

database_url = os.environ.get("DATABASE_URL")
db_engine = env("DB_ENGINE", default="sqlite").lower()
if database_url:
    DATABASES = {
        "default": dj_database_url.parse(database_url, conn_max_age=600, ssl_require=not DEBUG)
    }
elif db_engine == "postgresql":
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": env("DB_NAME"),
            "USER": env("DB_USER"),
            "PASSWORD": env("DB_PASSWORD"),
            "HOST": env("DB_HOST", default="localhost"),
            "PORT": env("DB_PORT", default="5432"),
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / env("DB_NAME", default="db.sqlite3"),
        }
    }

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "ru"
TIME_ZONE = "Asia/Qyzylorda"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}
WHITENOISE_USE_FINDERS = True
WHITENOISE_AUTOREFRESH = DEBUG
WHITENOISE_MANIFEST_STRICT = False
MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

CSRF_TRUSTED_ORIGINS = env("CSRF_TRUSTED_ORIGINS")
if RENDER_EXTERNAL_HOSTNAME:
    CSRF_TRUSTED_ORIGINS.append(f"https://{RENDER_EXTERNAL_HOSTNAME}")

SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "dashboard:index"
LOGOUT_REDIRECT_URL = "login"

MAX_UPLOAD_SIZE_MB = env("MAX_UPLOAD_SIZE_MB")
MAX_VOICE_MESSAGE_SIZE_MB = env("MAX_VOICE_MESSAGE_SIZE_MB")
# Seconds a recognised command waits, cancellable, before it runs itself. Only
# ordinary forward steps get the countdown - see may_auto_confirm(). Set to 0 to
# go back to requiring a press for everything.
VOICE_AUTOCONFIRM_SECONDS = env("VOICE_AUTOCONFIRM_SECONDS")
PROCESS_MINING_API_URL = env("PROCESS_MINING_API_URL", default="")
PROCESS_MINING_API_TOKEN = env("PROCESS_MINING_API_TOKEN", default="")
PROCESS_MINING_CALLBACK_URL = env("PROCESS_MINING_CALLBACK_URL", default="")
PROCESS_MINING_CALLBACK_SECRET = env("PROCESS_MINING_CALLBACK_SECRET", default="")
PROCESS_MINING_TIMEOUT_SECONDS = env("PROCESS_MINING_TIMEOUT_SECONDS")
PROCESS_MINING_EVENT_LOG_URL = env("PROCESS_MINING_EVENT_LOG_URL", default="")
PROCESS_MINING_SOURCE = env("PROCESS_MINING_SOURCE", default="kms_bakery")
PROCESS_MINING_SCHEMA_VERSION = env("PROCESS_MINING_SCHEMA_VERSION", default="1.0")
PROCESS_MINING_BATCH_SIZE = env("PROCESS_MINING_BATCH_SIZE")
PROCESS_MINING_EXPORT_INTERVAL_SECONDS = env("PROCESS_MINING_EXPORT_INTERVAL_SECONDS")
PROCESS_MINING_MAX_RETRIES = env("PROCESS_MINING_MAX_RETRIES")
PROCESS_MINING_CONNECT_TIMEOUT = env("PROCESS_MINING_CONNECT_TIMEOUT")
PROCESS_MINING_READ_TIMEOUT = env("PROCESS_MINING_READ_TIMEOUT")
ALLOWED_UPLOAD_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".webp", ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".csv", ".txt"
}
ALLOWED_VOICE_EXTENSIONS = {".webm", ".ogg", ".mp3", ".wav", ".m4a"}

REST_FRAMEWORK = {
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "DEFAULT_FILTER_BACKENDS": [
        "django_filters.rest_framework.DjangoFilterBackend",
        "rest_framework.filters.SearchFilter",
        "rest_framework.filters.OrderingFilter",
    ],
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 25,
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
}

SPECTACULAR_SETTINGS = {
    "TITLE": "QMS API",
    "DESCRIPTION": "REST API системы управления качеством производства.",
    "VERSION": "1.0.0",
}
