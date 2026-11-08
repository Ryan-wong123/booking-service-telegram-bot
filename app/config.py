"""Configuration, read from environment variables (never hardcode secrets)."""
import os
from datetime import timedelta


def _bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def load_config() -> dict:
    env = os.environ.get("APP_ENV", "development")
    db_url = os.environ.get("DATABASE_URL", "sqlite:///bookings.db")
    if db_url.startswith("postgres://"):
        db_url = db_url.replace("postgres://", "postgresql://", 1)
    production = env == "production"
    return {
        "APP_ENV": env,
        "SECRET_KEY": os.environ.get("SECRET_KEY"),
        "SQLALCHEMY_DATABASE_URI": db_url,
        "SQLALCHEMY_ENGINE_OPTIONS": {"pool_pre_ping": True},
        "SESSION_COOKIE_HTTPONLY": True,
        "SESSION_COOKIE_SAMESITE": "Lax",
        "SESSION_COOKIE_SECURE": _bool("SESSION_COOKIE_SECURE", production),
        "PERMANENT_SESSION_LIFETIME": timedelta(hours=int(os.environ.get("SESSION_HOURS", "8"))),
        "TRUST_PROXY": _bool("TRUST_PROXY", production),
        # Business rules
        "APP_TIMEZONE": os.environ.get("APP_TIMEZONE", "Asia/Singapore"),
        "MAX_ACTIVE_BOOKINGS": int(os.environ.get("MAX_ACTIVE_BOOKINGS", "3")),
        "ALLOW_REGISTRATION": _bool("ALLOW_REGISTRATION", True),
        "LOCKOUT_ATTEMPTS": int(os.environ.get("LOCKOUT_ATTEMPTS", "5")),
        "LOCKOUT_MINUTES": int(os.environ.get("LOCKOUT_MINUTES", "15")),
        "MIN_PASSWORD_LENGTH": int(os.environ.get("MIN_PASSWORD_LENGTH", "10")),
        # Optional Zoom (Server-to-Server OAuth). Disabled unless all three are set.
        "ZOOM_ACCOUNT_ID": os.environ.get("ZOOM_ACCOUNT_ID"),
        "ZOOM_CLIENT_ID": os.environ.get("ZOOM_CLIENT_ID"),
        "ZOOM_CLIENT_SECRET": os.environ.get("ZOOM_CLIENT_SECRET"),
        # First-run bootstrap of the super admin (used by `flask init-db`)
        "SUPERADMIN_EMAIL": os.environ.get("SUPERADMIN_EMAIL"),
        "SUPERADMIN_PASSWORD": os.environ.get("SUPERADMIN_PASSWORD"),
        "SUPERADMIN_NAME": os.environ.get("SUPERADMIN_NAME", "Super Admin"),
    }
