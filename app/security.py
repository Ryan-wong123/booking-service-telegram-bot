import hashlib
import hmac
from functools import wraps
from urllib.parse import urlparse

from flask import abort, current_app
from flask_login import current_user, login_required

from .extensions import db
from itsdangerous import BadSignature, URLSafeTimedSerializer

from .models import AuditLog, User


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


# ---- password reset tokens (stateless, single use, expire) ----
def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(current_app.config["SECRET_KEY"], salt="password-reset")


def _fingerprint(user) -> str:
    # Changes whenever the password changes, so a used token (or an old one) stops working.
    return hashlib.sha256(user.password_hash.encode()).hexdigest()[:20]


def make_reset_token(user) -> str:
    return _serializer().dumps({"uid": user.id, "fp": _fingerprint(user)})


def load_reset_token(token: str):
    try:
        data = _serializer().loads(token, max_age=current_app.config["RESET_TOKEN_MINUTES"] * 60)
    except BadSignature:  # includes SignatureExpired
        return None
    user = db.session.get(User, data.get("uid"))
    if user and user.active and hmac.compare_digest(data.get("fp", ""), _fingerprint(user)):
        return user
    return None
