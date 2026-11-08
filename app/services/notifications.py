"""Every email the portal sends. Failures are logged and never break a booking."""
import logging
from datetime import timedelta

from flask import current_app, has_request_context, url_for

from ..extensions import db
from ..models import CONFIRMED, Booking, Slot
from ..timeutils import to_local, utcnow
from .email import send_email

log = logging.getLogger(__name__)


def _when(dt) -> str:
    return to_local(dt).strftime("%A %d %B %Y, %H:%M")


def _link(endpoint: str, **values) -> str:
    """Absolute link built from APP_BASE_URL; works inside and outside a web request (e.g. the reminder job)."""
    base = current_app.config["APP_BASE_URL"].rstrip("/")
    if has_request_context():
        return base + url_for(endpoint, **values)
    with current_app.test_request_context():
        return base + url_for(endpoint, **values)


def _details(booking: Booking) -> str:
    slot = booking.slot
    lines = [
        f"Service: {slot.service.name}",
        f"When:    {_when(slot.start_at)} - {to_local(slot.end_at).strftime('%H:%M')} ({current_app.config['APP_TIMEZONE']})",
        f"With:    {slot.staff.name}",
    ]
    if booking.zoom_link:
        lines.append(f"Zoom:    {booking.zoom_link}")
    elif slot.service.use_zoom:
        lines.append("Zoom:    your host will share the meeting link")
    return "\n".join(lines)


def _safe(fn):
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except Exception:
            log.exception("Notification %s failed", fn.__name__)
            return False

    return wrapper


@_safe
def booking_confirmed(booking: Booking) -> None:
    slot, customer = booking.slot, booking.customer
    send_email(
        customer.email,
        f"Booking confirmed: {slot.service.name}, {to_local(slot.start_at):%d %b %H:%M}",
        f"Hi {customer.name},\n\nYour appointment is confirmed.\n\n{_details(booking)}\n\n"
        f"Manage it here: {_link('customer.my_bookings')}\n",
    )
    notes = f"\nNote from customer: {booking.notes}" if booking.notes else ""
    send_email(
        slot.staff.email,
        f"New booking: {customer.name}, {to_local(slot.start_at):%d %b %H:%M}",
        f"Hi {slot.staff.name},\n\n{customer.name} ({customer.email}) booked a slot with you.\n\n"
        f"{_details(booking)}{notes}\n\nYour schedule: {_link('staff.dashboard')}\n",
    )


@_safe
def booking_cancelled(booking: Booking, actor) -> None:
    slot, customer = booking.slot, booking.customer
    reason = f"\nReason: {booking.cancel_reason}" if booking.cancel_reason else ""
    summary = (
        f"Service: {slot.service.name}\nWhen:    {_when(slot.start_at)} ({current_app.config['APP_TIMEZONE']})\n"
        f"Customer: {customer.name}\nHost:    {slot.staff.name}"
    )
    for person in {customer.id: customer, slot.staff.id: slot.staff}.values():
        if person.id == actor.id:
            continue  # the person who cancelled already knows
        send_email(
            person.email,
            f"Booking cancelled: {slot.service.name}, {to_local(slot.start_at):%d %b %H:%M}",
            f"Hi {person.name},\n\nThis booking was cancelled by {actor.name}.{reason}\n\n{summary}\n",
        )


@_safe
def booking_rescheduled(booking: Booking, old_start, old_staff) -> None:
    slot, customer = booking.slot, booking.customer
    body = (
        f"The booking previously on {_when(old_start)} has moved.\n\nNew details:\n{_details(booking)}\n\n"
        f"Customer: {customer.name}"
    )
    send_email(customer.email, f"Booking rescheduled: {slot.service.name}", f"Hi {customer.name},\n\n{body}\n")
    for person in {old_staff.id: old_staff, slot.staff.id: slot.staff}.values():
        send_email(person.email, f"Booking rescheduled: {customer.name}", f"Hi {person.name},\n\n{body}\n")


@_safe
def reminder(booking: Booking) -> bool:
    slot, customer = booking.slot, booking.customer
    return send_email(
        customer.email,
        f"Reminder: {slot.service.name} on {to_local(slot.start_at):%d %b at %H:%M}",
        f"Hi {customer.name},\n\nThis is a reminder of your upcoming appointment.\n\n{_details(booking)}\n\n"
        f"Need to change it? {_link('customer.my_bookings')}\n",
        wait=True,
    )


@_safe
def password_reset(user, url: str, minutes: int) -> None:
    send_email(
        user.email,
        "Reset your Booking Portal password",
        f"Hi {user.name},\n\nUse this link to choose a new password (valid for {minutes} minutes, single use):\n\n{url}\n\n"
        "If you didn't ask for this, you can ignore this email; your password has not changed.\n",
    )


def needs_reminder_now(slot_start) -> bool:
    """True if a booking this close to its start needs no separate reminder (it was just made)."""
    return slot_start <= utcnow() + timedelta(hours=current_app.config["REMINDER_HOURS"])


def send_due_reminders() -> int:
    """Send reminders for confirmed bookings starting within REMINDER_HOURS. Idempotent and safe to run
    from several replicas or a CronJob: a booking is marked once its reminder is delivered."""
    now = utcnow()
    horizon = now + timedelta(hours=current_app.config["REMINDER_HOURS"])
    due = (
        Booking.query.join(Slot, Booking.slot_id == Slot.id)
        .filter(
            Booking.status == CONFIRMED,
            Booking.reminder_sent_at.is_(None),
            Slot.start_at > now,
            Slot.start_at <= horizon,
        )
        .all()
    )
    sent = 0
    for booking in due:
        if reminder(booking):
            booking.reminder_sent_at = utcnow()
            db.session.commit()
            sent += 1
    return sent
