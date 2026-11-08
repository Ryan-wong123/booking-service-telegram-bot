"""Optional Zoom integration. Every failure is logged and swallowed: a Zoom outage
must never block or corrupt a booking."""
import logging
import time
from datetime import datetime

import httpx
from flask import current_app

log = logging.getLogger(__name__)

_token_cache = {"token": None, "expires_at": 0.0}


def enabled() -> bool:
    cfg = current_app.config
    return all(cfg.get(k) for k in ("ZOOM_ACCOUNT_ID", "ZOOM_CLIENT_ID", "ZOOM_CLIENT_SECRET"))


def _token() -> str:
    if _token_cache["token"] and _token_cache["expires_at"] > time.time() + 60:
        return _token_cache["token"]
    cfg = current_app.config
    resp = httpx.post(
        "https://zoom.us/oauth/token",
        data={"grant_type": "account_credentials", "account_id": cfg["ZOOM_ACCOUNT_ID"]},
        auth=(cfg["ZOOM_CLIENT_ID"], cfg["ZOOM_CLIENT_SECRET"]),
        timeout=10,
    )
    resp.raise_for_status()
    body = resp.json()
    _token_cache["token"] = body["access_token"]
    _token_cache["expires_at"] = time.time() + int(body.get("expires_in", 3600))
    return _token_cache["token"]


def create_meeting(topic: str, start_utc: datetime, duration_minutes: int):
    """Return (meeting_id, join_url) for a scheduled meeting, or None on any failure."""
    if not enabled():
        return None
    try:
        resp = httpx.post(
            "https://api.zoom.us/v2/users/me/meetings",
            headers={"Authorization": f"Bearer {_token()}"},
            json={
                "topic": topic,
                "type": 2,  # scheduled meeting (type 1 is an instant meeting)
                "start_time": start_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "duration": duration_minutes,
                "timezone": "UTC",
            },
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        return str(data["id"]), data["join_url"]
    except Exception:
        log.exception("Zoom meeting creation failed")
        return None


def delete_meeting(meeting_id: str | None) -> None:
    if not meeting_id or not enabled():
        return
    try:
        resp = httpx.delete(
            f"https://api.zoom.us/v2/meetings/{meeting_id}",
            headers={"Authorization": f"Bearer {_token()}"},
            timeout=10,
        )
        if resp.status_code not in (204, 404):
            resp.raise_for_status()
    except Exception:
        log.exception("Zoom meeting deletion failed for %s", meeting_id)
