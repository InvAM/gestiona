"""Gestiona settings. All environment-specific values come from env vars (see .env.example)."""

from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parent.parent

env = environ.Env(
    DEBUG=(bool, False),
    ALLOWED_HOSTS=(list, ["localhost", "127.0.0.1"]),
    CSRF_TRUSTED_ORIGINS=(list, ["http://localhost:3000"]),
    FRONTEND_URL=(str, "http://localhost:3000"),
    USE_S3=(bool, False),
    SSO_GOOGLE_ENABLED=(bool, False),
    SSO_MICROSOFT_ENABLED=(bool, False),
    SSO_OIDC_ENABLED=(bool, False),
    ALLOWED_SIGNUP_DOMAINS=(list, []),
    PASSWORD_LOGIN_ENABLED=(bool, True),
)
environ.Env.read_env(BASE_DIR.parent / ".env")
environ.Env.read_env(BASE_DIR / ".env")

SECRET_KEY = env("SECRET_KEY", default="dev-insecure-change-me")
DEBUG = env("DEBUG")
ALLOWED_HOSTS = env("ALLOWED_HOSTS")
CSRF_TRUSTED_ORIGINS = env("CSRF_TRUSTED_ORIGINS")
FRONTEND_URL = env("FRONTEND_URL")

if not DEBUG and SECRET_KEY.startswith("dev-"):
    raise RuntimeError("SECRET_KEY must be set in production")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.postgres",
    # third party
    "ninja",
    "channels",
    "allauth",
    "allauth.account",
    "allauth.socialaccount",
    "allauth.socialaccount.providers.google",
    "allauth.socialaccount.providers.microsoft",
    "allauth.socialaccount.providers.openid_connect",
    "allauth.headless",
    "storages",
    # gestiona
    "apps.core",
    "apps.accounts",
    "apps.projects",
    "apps.workflows",
    "apps.issues",
    "apps.boards",
    "apps.search",
    "apps.notifications",
    "apps.imports",
    "apps.automation",
    "apps.dashboards",
    "apps.audit",
    "apps.forms",
    "apps.ai",
    "apps.plans",
    "apps.analytics",
    "apps.listview",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "allauth.account.middleware.AccountMiddleware",
    "apps.audit.middleware.AuditMiddleware",
]

ROOT_URLCONF = "config.urls"

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

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

DATABASES = {
    "default": env.db("DATABASE_URL", default="postgres://gestiona:gestiona@localhost:5432/gestiona")
}
DATABASES["default"]["CONN_MAX_AGE"] = env.int("DB_CONN_MAX_AGE", default=60)
DATABASES["default"]["CONN_HEALTH_CHECKS"] = True

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
AUTH_USER_MODEL = "accounts.User"

AUTHENTICATION_BACKENDS = [
    "django.contrib.auth.backends.ModelBackend",
    "allauth.account.auth_backends.AuthenticationBackend",
]

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
     "OPTIONS": {"min_length": 10}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "es"
TIME_ZONE = env("TIME_ZONE", default="America/Lima")
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

# --- Storage (attachments) ---
if env("USE_S3"):
    STORAGES = {
        "default": {
            "BACKEND": "storages.backends.s3.S3Storage",
            "OPTIONS": {
                "bucket_name": env("S3_BUCKET", default="gestiona"),
                "endpoint_url": env("S3_ENDPOINT_URL", default=None),
                "access_key": env("S3_ACCESS_KEY", default=None),
                "secret_key": env("S3_SECRET_KEY", default=None),
                "region_name": env("S3_REGION", default="us-east-1"),
                "default_acl": None,
                "querystring_auth": True,
                "querystring_expire": 3600,
                "file_overwrite": False,
            },
        },
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    }
MAX_ATTACHMENT_MB = env.int("MAX_ATTACHMENT_MB", default=50)
DATA_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024

# --- Redis / Channels / Celery ---
REDIS_URL = env("REDIS_URL", default="redis://localhost:6379/0")
CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels_redis.core.RedisChannelLayer",
        # redis-py >= 8 defaults socket_timeout to 5s, which equals channels_redis' blocking
        # BZPOPMIN timeout and makes idle websocket consumers crash. Keep it well above.
        "CONFIG": {"hosts": [{"address": REDIS_URL, "socket_timeout": 30}]},
    }
}
CELERY_BROKER_URL = REDIS_URL
CELERY_RESULT_BACKEND = None
CELERY_TASK_ALWAYS_EAGER = env.bool("CELERY_TASK_ALWAYS_EAGER", default=False)
CELERY_TASK_ACKS_LATE = True
CELERY_TIMEZONE = TIME_ZONE
CELERY_BEAT_SCHEDULE = {
    "automation-tick": {"task": "apps.automation.tasks.tick", "schedule": 60.0},
    "audit-prune": {"task": "apps.audit.tasks.prune_audit", "schedule": 24 * 3600.0},
}
AUDIT_RETENTION_DAYS = env.int("AUDIT_RETENTION_DAYS", default=365)
AUTOMATION_WEBHOOK_ALLOW_PRIVATE = env.bool("AUTOMATION_WEBHOOK_ALLOW_PRIVATE", default=False)
# Allow Jira imports from private/internal addresses (Jira Server on-prem).
IMPORTS_ALLOW_PRIVATE = env.bool("IMPORTS_ALLOW_PRIVATE", default=False)

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": REDIS_URL,
    }
}

# --- Sessions / security ---
SESSION_COOKIE_NAME = "gestiona_session"
SESSION_COOKIE_AGE = 60 * 60 * 24 * 14
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_NAME = "gestiona_csrf"
CSRF_COOKIE_HTTPONLY = False  # frontend reads it to send X-CSRFToken
CSRF_COOKIE_SAMESITE = "Lax"
if not DEBUG:
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_SSL_REDIRECT = env.bool("SECURE_SSL_REDIRECT", default=True)
    SECURE_REDIRECT_EXEMPT = [r"^api/v1/health$"]  # container healthcheck over plain HTTP
    SECURE_HSTS_SECONDS = 60 * 60 * 24 * 30
    SECURE_CONTENT_TYPE_NOSNIFF = True
    SECURE_REFERRER_POLICY = "same-origin"
    X_FRAME_OPTIONS = "DENY"

# --- allauth (headless, session-based for the Next.js frontend) ---
ACCOUNT_LOGIN_METHODS = {"email"}
ACCOUNT_SIGNUP_FIELDS = ["email*", "password1*", "password2*"]
ACCOUNT_USER_MODEL_USERNAME_FIELD = None
ACCOUNT_EMAIL_VERIFICATION = env("ACCOUNT_EMAIL_VERIFICATION", default="optional")
ACCOUNT_UNIQUE_EMAIL = True
ACCOUNT_ADAPTER = "apps.accounts.adapters.AccountAdapter"
SOCIALACCOUNT_ADAPTER = "apps.accounts.adapters.SocialAccountAdapter"
SOCIALACCOUNT_EMAIL_AUTHENTICATION = True
SOCIALACCOUNT_EMAIL_AUTHENTICATION_AUTO_CONNECT = True
SOCIALACCOUNT_ONLY = not env("PASSWORD_LOGIN_ENABLED")
HEADLESS_ONLY = True
HEADLESS_FRONTEND_URLS = {
    "account_confirm_email": f"{FRONTEND_URL}/auth/verify-email/{{key}}",
    "account_reset_password_from_key": f"{FRONTEND_URL}/auth/reset-password/{{key}}",
    "account_signup": f"{FRONTEND_URL}/auth/signup",
    "socialaccount_login_error": f"{FRONTEND_URL}/auth/login?error=sso",
}
# Restrict who can create an account (empty list = invite-only via admin).
ALLOWED_SIGNUP_DOMAINS = [d.lower() for d in env("ALLOWED_SIGNUP_DOMAINS")]

SOCIALACCOUNT_PROVIDERS: dict = {}
if env("SSO_GOOGLE_ENABLED"):
    SOCIALACCOUNT_PROVIDERS["google"] = {
        "APPS": [{
            "client_id": env("GOOGLE_CLIENT_ID"),
            "secret": env("GOOGLE_CLIENT_SECRET"),
        }],
        "SCOPE": ["profile", "email"],
        "AUTH_PARAMS": {"prompt": "select_account"},
    }
if env("SSO_MICROSOFT_ENABLED"):
    SOCIALACCOUNT_PROVIDERS["microsoft"] = {
        "APPS": [{
            "client_id": env("MICROSOFT_CLIENT_ID"),
            "secret": env("MICROSOFT_CLIENT_SECRET"),
            "settings": {"tenant": env("MICROSOFT_TENANT", default="organizations")},
        }],
    }

if env("SSO_OIDC_ENABLED"):
    # Any OpenID Connect IdP: Okta, Keycloak, Authentik, Entra ID, Google Workspace, Auth0...
    # Callback: https://<dominio>/accounts/oidc/login/callback/
    SOCIALACCOUNT_PROVIDERS["openid_connect"] = {
        "OAUTH_PKCE_ENABLED": True,
        "APPS": [{
            "provider_id": "oidc",
            "name": env("OIDC_NAME", default="SSO de la empresa"),
            "client_id": env("OIDC_CLIENT_ID"),
            "secret": env("OIDC_CLIENT_SECRET"),
            "settings": {"server_url": env("OIDC_SERVER_URL")},
        }],
    }

# --- AI assistant (optional; off unless a key is set) ---
ANTHROPIC_API_KEY = env("ANTHROPIC_API_KEY", default="")
AI_MODEL = env("AI_MODEL", default="claude-opus-5-5")
AI_EFFORT = env("AI_EFFORT", default="low")  # short interactive tasks: low keeps them snappy

# --- Email ---
_email_backend = env("EMAIL_BACKEND", default="django.core.mail.backends.console.EmailBackend")
MAILERS = {
    "default": {
        "BACKEND": _email_backend,
        "OPTIONS": {
            "host": env("EMAIL_HOST", default="localhost"),
            "port": env.int("EMAIL_PORT", default=587),
            "username": env("EMAIL_HOST_USER", default=""),
            "password": env("EMAIL_HOST_PASSWORD", default=""),
            "use_tls": env.bool("EMAIL_USE_TLS", default=True),
            "timeout": 15,
        } if _email_backend.endswith("smtp.EmailBackend") else {},
    }
}
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", default="Gestiona <no-reply@localhost>")


LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"std": {"format": "%(asctime)s %(levelname)s %(name)s %(message)s"}},
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "std"}},
    "root": {"handlers": ["console"], "level": env("LOG_LEVEL", default="INFO")},
}
