from functools import wraps
from urllib.parse import urlparse

from flask import abort
from flask_login import current_user, login_required

from .extensions import db
from .models import AuditLog


def roles_required(*roles):
    def decorator(view):
        @wraps(view)
        def wrapper(*args, **kwargs):
            if current_user.role not in roles:
                abort(403)
            return view(*args, **kwargs)

        return login_required(wrapper)

    return decorator


def is_safe_next(target: str | None) -> bool:
    """Only allow same-site relative redirects (prevents open redirect)."""
    if not target:
        return False
    parsed = urlparse(target)
    return not parsed.netloc and not parsed.scheme and target.startswith("/") and not target.startswith("//")


def audit(action: str, detail: str = "", actor=None) -> None:
    """Add an audit row to the current session; the caller commits."""
    actor_id = getattr(actor, "id", None)
    db.session.add(AuditLog(actor_id=actor_id, action=action, detail=detail[:500]))
