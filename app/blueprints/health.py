from flask import Blueprint, jsonify
from sqlalchemy import text

from ..extensions import db

bp = Blueprint("health", __name__)


@bp.get("/healthz")
def healthz():
    """Liveness: the process is up."""
    return jsonify(status="ok")


@bp.get("/readyz")
def readyz():
    """Readiness: the database answers."""
    try:
        db.session.execute(text("SELECT 1"))
    except Exception:
        return jsonify(status="database unavailable"), 503
    return jsonify(status="ready")
