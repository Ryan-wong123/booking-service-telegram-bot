"""Plain-text email over SMTP (works with Amazon SES SMTP). Never raises into a request."""
import logging
import smtplib
import threading
from email.message import EmailMessage

from flask import current_app

log = logging.getLogger(__name__)


def enabled() -> bool:
    return bool(current_app.config.get("SMTP_HOST"))


def _deliver(config: dict, msg: EmailMessage) -> bool:
    try:
        with smtplib.SMTP(config["SMTP_HOST"], config["SMTP_PORT"], timeout=15) as smtp:
            smtp.ehlo()
            if config["SMTP_STARTTLS"]:
                smtp.starttls()
                smtp.ehlo()
            if config["SMTP_USERNAME"]:
                smtp.login(config["SMTP_USERNAME"], config["SMTP_PASSWORD"] or "")
            smtp.send_message(msg)
        return True
    except Exception:
        log.exception("Failed to send email to %s (%s)", msg["To"], msg["Subject"])
        return False


def send_email(to: str, subject: str, body: str, wait: bool = False) -> bool:
    """Send one email. Request handlers use wait=False (background thread, returns True optimistically);
    the reminder job uses wait=True so it only marks a reminder as sent when delivery succeeded."""
    app = current_app._get_current_object()
    msg = EmailMessage()
    msg["From"] = app.config["MAIL_FROM"]
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)

    if app.config.get("TESTING"):
        app.extensions.setdefault("outbox", []).append(msg)
        return True
    if not enabled():
        log.warning("SMTP not configured; email not sent: to=%s subject=%s", to, subject)
        return False
    config = dict(app.config)
    if wait:
        return _deliver(config, msg)
    threading.Thread(target=_deliver, args=(config, msg), daemon=True).start()
    return True
