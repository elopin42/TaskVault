"""Django settings for TaskVault (the code keeps the `lowbid` package name).

Every environment-specific value is read from the environment (a `.env` file at
the repo root is loaded by python-dotenv; see `.env.example`). Defaults target
the hackathon laptop: SQLite under data/, whitenoise for static files, Stellar
testnet.
"""

import logging
import os
from decimal import Decimal
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent


def _csv(name: str, default: str = "") -> list[str]:
    raw = os.environ.get(name, default)
    return [item.strip() for item in raw.split(",") if item.strip()]


def _bool(name: str, default: str = "0") -> bool:
    return os.environ.get(name, default).strip().lower() in ("1", "true", "yes", "on")


# --- Security / debug ---------------------------------------------------------

DEBUG = _bool("DJANGO_DEBUG", "0")

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "").strip()
if not SECRET_KEY:
    if DEBUG:
        # Dev-only fallback: never let a production boot run on a known key.
        SECRET_KEY = "lowbid-dev-only-insecure-secret-key-change-me"
    else:
        raise ImproperlyConfigured("DJANGO_SECRET_KEY is required when DJANGO_DEBUG is off")

ALLOWED_HOSTS = _csv("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1,0.0.0.0")
CSRF_TRUSTED_ORIGINS = _csv("DJANGO_CSRF_TRUSTED_ORIGINS")

FORCE_HTTPS = _bool("DJANGO_FORCE_HTTPS", "0")

# --- Applications ---------------------------------------------------------------

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    # Let whitenoise serve static files under runserver too (same code path as prod).
    "whitenoise.runserver_nostatic",
    "django.contrib.staticfiles",
    # TaskVault apps
    "core",
    "accounts",
    "projects",
    "payments",
    "dashboard",
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
]

ROOT_URLCONF = "lowbid.urls"

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
                "core.context_processors.site",
                "core.context_processors.nav_links",
                "accounts.context_processors.wallet",
            ],
        },
    },
]

WSGI_APPLICATION = "lowbid.wsgi.application"

# --- Database -----------------------------------------------------------------
# SQLite by default (file under data/, gitignored). Setting DJANGO_DB_HOST switches
# to PostgreSQL with the same DJANGO_DB_* names SIPS uses.

if os.environ.get("DJANGO_DB_HOST"):
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": os.environ.get("DJANGO_DB_NAME", "lowbid"),
            "USER": os.environ.get("DJANGO_DB_USER", "lowbid"),
            "PASSWORD": os.environ.get("DJANGO_DB_PASSWORD", ""),
            "HOST": os.environ["DJANGO_DB_HOST"],
            "PORT": os.environ.get("DJANGO_DB_PORT", "5432"),
            "CONN_MAX_AGE": 60,
            "CONN_HEALTH_CHECKS": True,
        }
    }
else:
    _data_dir = BASE_DIR / "data"
    _data_dir.mkdir(exist_ok=True)
    # LOWBID_SQLITE_PATH lets a throwaway run (make e2e) use its own file.
    _sqlite_path = Path(os.environ.get("LOWBID_SQLITE_PATH", "").strip() or (_data_dir / "db.sqlite3"))
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": _sqlite_path,
        }
    }

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
]

# --- i18n ---------------------------------------------------------------------

LANGUAGE_CODE = "en-us"
TIME_ZONE = os.environ.get("DJANGO_TIME_ZONE", "Europe/Paris")
USE_I18N = True
USE_TZ = True

# --- Sessions / cookies -------------------------------------------------------
# Identity is a Stellar wallet: the session carries wallet_address + wallet_user_id
# (see accounts.views.auth_verify). 8 hours, not refreshed per request.

SESSION_COOKIE_AGE = 60 * 60 * 8
SESSION_SAVE_EVERY_REQUEST = False
SESSION_COOKIE_NAME = "lowbid_sessionid"
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_SECURE = FORCE_HTTPS
CSRF_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SECURE = FORCE_HTTPS
SECURE_SSL_REDIRECT = FORCE_HTTPS
SECURE_REDIRECT_EXEMPT = [r"^healthz/$"]
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https") if FORCE_HTTPS else None

# Lifetime of a login challenge (nonce) before the browser must ask for a new one.
WALLET_CHALLENGE_TTL_SECONDS = int(os.environ.get("WALLET_CHALLENGE_TTL_SECONDS", "300"))

# --- Static files (whitenoise) --------------------------------------------------

STATIC_URL = "/static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"
# whitenoise warns at boot when STATIC_ROOT is missing; the dir is gitignored, so create it.
STATIC_ROOT.mkdir(exist_ok=True)
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    # Compressed but NOT manifest-hashed: cache-busting is the explicit
    # ?v={{ LOWBID_ASSET_VERSION }} suffix in templates, so tests and `runserver`
    # never need a collectstatic pass first.
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedStaticFilesStorage"},
}
WHITENOISE_MAX_AGE = 0 if DEBUG else 60 * 60 * 24 * 30

# Bump whenever css/lowbid-*.css or js/lowbid-*.js changes (30-day static cache).
LOWBID_ASSET_VERSION = os.environ.get("LOWBID_ASSET_VERSION", "").strip() or "20261025-fingerprint"

# --- Stellar ------------------------------------------------------------------

STELLAR_NETWORK = os.environ.get("STELLAR_NETWORK", "testnet").strip().lower()
STELLAR_NETWORK_PASSPHRASE = {
    "testnet": "Test SDF Network ; September 2015",
    "public": "Public Global Stellar Network ; September 2015",
    "futurenet": "Test SDF Future Network ; October 2022",
}.get(STELLAR_NETWORK, "Test SDF Network ; September 2015")
STELLAR_HORIZON_URL = os.environ.get("STELLAR_HORIZON_URL", "https://horizon-testnet.stellar.org").rstrip("/")
STELLAR_SOROBAN_RPC_URL = os.environ.get("STELLAR_SOROBAN_RPC_URL", "https://soroban-testnet.stellar.org").rstrip("/")
# Circle USDC issuer on testnet; override for mainnet. Legacy names, still honoured.
STELLAR_USDC_ISSUER = os.environ.get("STELLAR_USDC_ISSUER", "GBBD47IF6LWK7P7MDEVSCWR7DPUWV3NY3DTQEVFL4NAT4AQH3ZLLFLA5").strip()
STELLAR_USDC_CODE = os.environ.get("STELLAR_USDC_CODE", "USDC").strip() or "USDC"
# The payment asset (payments.stellar.asset()): defaults to the USDC values above. CODE=XLM with an
# EMPTY issuer means the native asset — direct payments and balances work, the Trustless Work escrow
# does not (it needs an issuer), so payment_mode() falls back to "direct" with a warning.
STELLAR_ASSET_CODE = (os.environ.get("STELLAR_ASSET_CODE", "").strip() or STELLAR_USDC_CODE).upper()
STELLAR_ASSET_ISSUER = os.environ.get("STELLAR_ASSET_ISSUER", STELLAR_USDC_ISSUER).strip()
TRUSTLESS_WORK_API_URL = os.environ.get("TRUSTLESS_WORK_API_URL", "https://dev.api.trustlesswork.com").rstrip("/")
TRUSTLESS_WORK_API_KEY = os.environ.get("TRUSTLESS_WORK_API_KEY", "")
# Plan B switch — "escrow" (Trustless Work) | "direct" (one USDC payment op) | "" (auto:
# escrow when TRUSTLESS_WORK_API_KEY is set, else direct). Read via payments.stellar.payment_mode().
LOWBID_PAYMENT_MODE = os.environ.get("LOWBID_PAYMENT_MODE", "").strip().lower()
# Platform wallet (G…): escrow disputeResolver + platformAddress (fee receiver; needs a USDC trustline).
LOWBID_PLATFORM_ADDRESS = os.environ.get("LOWBID_PLATFORM_ADDRESS", "").strip()
# Trustless Work v1 `platformFee` (JSON number). Unit unverified (bps vs percent) — keep 1 until
# a get-escrow read-back on testnet settles it (docs/STELLAR_NOTES.md §1.3).
LOWBID_PLATFORM_FEE = Decimal(os.environ.get("LOWBID_PLATFORM_FEE", "1").strip() or "1")

# --- Logging ------------------------------------------------------------------
# Structured key=value lines on stdout; level from DJANGO_LOG_LEVEL (default INFO).

DJANGO_LOG_LEVEL = os.environ.get("DJANGO_LOG_LEVEL", "INFO").strip().upper()
if DJANGO_LOG_LEVEL not in logging.getLevelNamesMapping():
    DJANGO_LOG_LEVEL = "INFO"

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "keyvalue": {"format": "level=%(levelname)s logger=%(name)s time=%(asctime)s msg=%(message)s"},
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "keyvalue"},
    },
    "root": {"handlers": ["console"], "level": DJANGO_LOG_LEVEL},
    "loggers": {
        "django": {"handlers": ["console"], "level": DJANGO_LOG_LEVEL, "propagate": False},
    },
}
