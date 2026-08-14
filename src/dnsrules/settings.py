"""Settings for dnsrules.

Every value comes from a `DNSRULES_` environment variable with a working
default. This module must import with an empty environment, because the
install procedure runs commands before the environment file exists.
"""

import os
import secrets
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent


def env(name: str, default: str = "") -> str:
    return os.environ.get(f"DNSRULES_{name}", default)


def env_bool(name: str, default: bool = False) -> bool:
    return env(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


def env_list(name: str, default: str = "") -> list[str]:
    return [item.strip() for item in env(name, default).split(",") if item.strip()]


# A generated key is per process, so a restart ends every session. Set
# DNSRULES_SECRET_KEY to keep sessions across restarts. More than one web
# worker requires it, otherwise workers reject each other's cookies.
SECRET_KEY = env("SECRET_KEY") or secrets.token_urlsafe(64)

DEBUG = env_bool("DEBUG")

# The panel answers on plain HTTP on the LAN, so host and origin checks are the
# main defence against DNS rebinding. Keep both lists explicit.
ALLOWED_HOSTS = env_list("ALLOWED_HOSTS", "localhost,127.0.0.1,[::1]")
CSRF_TRUSTED_ORIGINS = env_list("CSRF_TRUSTED_ORIGINS")

# Read by `serve`. Binding every interface is deliberate: the LAN has to reach
# the site, and nftables decides who does. ALLOWED_HOSTS is the check that
# matters here, because it stops DNS rebinding.
BIND = env("BIND", "0.0.0.0:8000")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    # For the BRIN index on the query log.
    "django.contrib.postgres",
    "whitenoise.runserver_nostatic",
    "django.contrib.staticfiles",
    "django_htmx",
    "dnsrules.core",
    "dnsrules.queries",
    "dnsrules.rules",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "django_htmx.middleware.HtmxMiddleware",
]

ROOT_URLCONF = "dnsrules.urls"

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

WSGI_APPLICATION = "dnsrules.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": env("DB_NAME", "dnsrules"),
        "USER": env("DB_USER", "dnsrules"),
        "PASSWORD": env("DB_PASSWORD"),
        "HOST": env("DB_HOST", "localhost"),
        "PORT": env("DB_PORT", "5432"),
        # verify-full, not require: require encrypts but verifies nothing.
        "OPTIONS": {"sslmode": env("DB_SSLMODE", "prefer")},
    }
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"


# unbound connects out to this address, so dnsrules listens on it. Loopback
# only: the stream is every DNS query in the house.
DNSTAP_HOST = env("DNSTAP_HOST", "127.0.0.1")
DNSTAP_PORT = int(env("DNSTAP_PORT", "6000"))

# unbound's remote control, with `control-use-cert: no` so there is no
# certificate to manage. Loopback only: plain text control hands the resolver
# to anyone who reaches the port. `just unbound` publishes 8953 for development.
UNBOUND_CONTROL_HOST = env("CONTROL_HOST", "127.0.0.1")
UNBOUND_CONTROL_PORT = int(env("CONTROL_PORT", "8953"))

# The rules zone. dnsrules serves it at `/rpz/<RPZ_NAME>.zone`, and unbound.conf
# names it RPZ_ZONE. Both must match unbound.conf, and both are read when the
# database is created. After that the row holds them.
RPZ_NAME = env("RPZ_NAME", "dnsrules")
RPZ_ZONE = env("RPZ_ZONE", "dnsrules")

_VALIDATION = "django.contrib.auth.password_validation"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": f"{_VALIDATION}.UserAttributeSimilarityValidator"},
    {"NAME": f"{_VALIDATION}.MinimumLengthValidator"},
    {"NAME": f"{_VALIDATION}.CommonPasswordValidator"},
    {"NAME": f"{_VALIDATION}.NumericPasswordValidator"},
]

PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.Argon2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
]

LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "dashboard"
LOGOUT_REDIRECT_URL = "login"

SESSION_COOKIE_AGE = 60 * 60 * 8
SESSION_COOKIE_SAMESITE = "Lax"

# Never force Secure. This is the tool you reach for when the proxy is down, so
# plain HTTP on the LAN has to keep working. Django sets Secure per request when
# that request already arrived over HTTPS.
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False

LANGUAGE_CODE = "en-us"
TIME_ZONE = env("TIME_ZONE", "UTC")
USE_I18N = False
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = env("STATIC_ROOT") or None

# One static home, inside the package, so the wheel carries every asset. It is
# not an app static directory, so nothing finds it twice.
STATICFILES_DIRS = [PACKAGE_DIR / "static"]

# Serve straight out of the installed package. This removes collectstatic from
# the install procedure, and the cost is nothing at this traffic.
WHITENOISE_USE_FINDERS = True
WHITENOISE_AUTOREFRESH = DEBUG
