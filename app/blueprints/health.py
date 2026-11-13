import os

from flask import Blueprint, current_app, jsonify
from sqlalchemy import text

from ..extensions import db

bp = Blueprint("health", __name__)


@bp.get("/healthz")
def healthz():
    """Liveness + load-balancer signal. Returns 503 while the instance is being drained for a deploy."""
    if os.path.exists(current_app.config["DRAIN_FILE"]):
        return jsonify(status="draining"), 503
    return jsonify(status="ok")


@bp.get("/readyz")
def readyz():
    """Readiness: the database answers."""
    try:
        db.session.execute(text("SELECT 1"))
    except Exception:
        return jsonify(status="database unavailable"), 503
    return jsonify(status="ready")
