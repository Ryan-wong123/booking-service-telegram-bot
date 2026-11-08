"""Booking business rules. Routes stay thin; every rule lives here."""
from datetime import datetime, timedelta

from flask import current_app
from sqlalchemy import and_, update

from ..extensions import db
from ..models import CANCELLED, COMPLETED, CONFIRMED, Booking, Service, Slot
from ..security import audit
from ..timeutils import utcnow
from . import notifications, zoom


class BookingError(Exception):
    """A user-facing rule violation."""


def _claim_slot(slot_id: int) -> bool:
    """Atomically mark a slot booked. Exactly one concurrent caller can win."""
    result = db.session.execute(
        update(Slot)
        .where(
            and_(
                Slot.id == slot_id,
                Slot.is_booked.is_(False),
                Slot.active.is_(True),
                Slot.start_at > utcnow(),
            )
        )
        .values(is_booked=True)
    )
    return result.rowcount == 1


def _active_count(customer_id: int) -> int:
    return (
        db.session.query(Booking)
        .join(Slot, Booking.slot_id == Slot.id)
        .filter(Booking.customer_id == customer_id, Booking.status == CONFIRMED, Slot.start_at > utcnow())
        .count()
    )


def _customer_overlap(customer_id: int, start: datetime, end: datetime, ignore_booking_id=None) -> bool:
    query = (
        db.session.query(Booking.id)
        .join(Slot, Booking.slot_id == Slot.id)
        .filter(
            Booking.customer_id == customer_id,
            Booking.status == CONFIRMED,
            Slot.start_at < end,
            Slot.end_at > start,
        )
    )
    if ignore_booking_id:
        query = query.filter(Booking.id != ignore_booking_id)
    return query.first() is not None


def _attach_zoom(booking: Booking) -> bool:
    """Create a Zoom meeting if the service wants one. Returns False if it was wanted but failed."""
    slot = booking.slot
    if not slot.service.use_zoom or not zoom.enabled():
        return True
    created = zoom.create_meeting(slot.service.name, slot.start_at, slot.service.duration_minutes)
    if not created:
        return False
    booking.zoom_meeting_id, booking.zoom_link = created
    db.session.commit()
    return True


def book_slot(customer, slot_id: int, notes: str = ""):
    """Returns (booking, zoom_ok)."""
    slot = db.session.get(Slot, slot_id)
    if not slot or not slot.active or not slot.service.active or not slot.staff.active:
        raise BookingError("That slot is no longer available.")
    if slot.start_at <= utcnow():
        raise BookingError("That slot is in the past.")
    if _active_count(customer.id) >= current_app.config["MAX_ACTIVE_BOOKINGS"]:
        raise BookingError(
            f"You can hold at most {current_app.config['MAX_ACTIVE_BOOKINGS']} upcoming bookings. "
            "Cancel one to book another."
        )
    if _customer_overlap(customer.id, slot.start_at, slot.end_at):
        raise BookingError("You already have a booking that overlaps this time.")
    if not _claim_slot(slot.id):
        db.session.rollback()
        raise BookingError("Sorry, someone just took that slot. Please pick another.")

    booking = Booking(slot_id=slot.id, customer_id=customer.id, notes=notes.strip()[:500])
    if notifications.needs_reminder_now(slot.start_at):
        booking.reminder_sent_at = utcnow()  # booked inside the reminder window: the confirmation is enough
    db.session.add(booking)
    audit("booking.create", f"slot={slot.id} customer={customer.id}", customer)
    db.session.commit()
    zoom_ok = _attach_zoom(booking)
    notifications.booking_confirmed(booking)
    return booking, zoom_ok


def cancel_booking(booking: Booking, actor, reason: str = "") -> None:
    if booking.status != CONFIRMED:
        raise BookingError("This booking can no longer be cancelled.")
    slot = booking.slot
    if slot.start_at <= utcnow():
        raise BookingError("Past bookings cannot be cancelled.")
    meeting_id = booking.zoom_meeting_id
    booking.status = CANCELLED
    booking.cancelled_by_id = actor.id
    booking.cancel_reason = reason.strip()[:300] or None
    booking.cancelled_at = utcnow()
    booking.zoom_meeting_id = None
    booking.zoom_link = None
    slot.is_booked = False
    audit("booking.cancel", f"booking={booking.id} reason={reason.strip()[:100]}", actor)
    db.session.commit()
    zoom.delete_meeting(meeting_id)  # best effort, after the DB is safe
    notifications.booking_cancelled(booking, actor)


def reschedule_booking(booking: Booking, new_slot_id: int, actor):
    """Move a confirmed booking to another free slot of the same service. Returns zoom_ok."""
    if booking.status != CONFIRMED or booking.slot.start_at <= utcnow():
        raise BookingError("Only upcoming confirmed bookings can be rescheduled.")
    new_slot = db.session.get(Slot, new_slot_id)
    if not new_slot or not new_slot.active or not new_slot.staff.active or new_slot.service_id != booking.slot.service_id:
        raise BookingError("Please choose a slot for the same service.")
    if new_slot.id == booking.slot_id:
        raise BookingError("You already hold that slot.")
    if _customer_overlap(booking.customer_id, new_slot.start_at, new_slot.end_at, ignore_booking_id=booking.id):
        raise BookingError("You already have a booking that overlaps this time.")
    if not _claim_slot(new_slot.id):
        db.session.rollback()
        raise BookingError("Sorry, someone just took that slot. Please pick another.")

    old_slot, old_meeting = booking.slot, booking.zoom_meeting_id
    old_start, old_staff = old_slot.start_at, old_slot.staff
    old_slot.is_booked = False
    booking.slot_id = new_slot.id
    booking.zoom_meeting_id = booking.zoom_link = None
    # New time -> the reminder is owed again unless the new slot is already inside the window.
    booking.reminder_sent_at = utcnow() if notifications.needs_reminder_now(new_slot.start_at) else None
    audit("booking.reschedule", f"booking={booking.id} {old_slot.id}->{new_slot.id}", actor)
    db.session.commit()
    zoom.delete_meeting(old_meeting)
    db.session.refresh(booking)
    zoom_ok = _attach_zoom(booking)
    notifications.booking_rescheduled(booking, old_start, old_staff)
    return zoom_ok


def complete_booking(booking: Booking, actor) -> None:
    if booking.status != CONFIRMED:
        raise BookingError("Only confirmed bookings can be completed.")
    if booking.slot.start_at > utcnow():
        raise BookingError("This appointment has not started yet.")
    booking.status = COMPLETED
    audit("booking.complete", f"booking={booking.id}", actor)
    db.session.commit()


def create_slots(staff, service: Service, start_utc: datetime, count: int) -> list[Slot]:
    """Create `count` back-to-back slots of the service's length, rejecting past/overlapping ones."""
    if not service.active:
        raise BookingError("That service is not active.")
    if not 1 <= count <= 20:
        raise BookingError("Create between 1 and 20 slots at a time.")
    if start_utc <= utcnow():
        raise BookingError("Slots must start in the future.")
    length = timedelta(minutes=service.duration_minutes)
    new = [
        (start_utc + length * i, start_utc + length * (i + 1)) for i in range(count)
    ]
    overall_start, overall_end = new[0][0], new[-1][1]
    clash = (
        db.session.query(Slot.id)
        .filter(
            Slot.staff_id == staff.id,
            Slot.active.is_(True),
            Slot.start_at < overall_end,
            Slot.end_at > overall_start,
        )
        .first()
    )
    if clash:
        raise BookingError("That time overlaps a slot you already have.")
    slots = [Slot(staff_id=staff.id, service_id=service.id, start_at=s, end_at=e) for s, e in new]
    db.session.add_all(slots)
    audit("slot.create", f"staff={staff.id} service={service.id} count={count} start={start_utc:%Y-%m-%d %H:%M}Z", staff)
    db.session.commit()
    return slots


def delete_slot(slot: Slot, actor) -> None:
    if slot.is_booked:
        raise BookingError("This slot is booked. Cancel the booking first.")
    _retire_slot(slot)
    audit("slot.delete", f"slot={slot.id}", actor)
    db.session.commit()


def _retire_slot(slot: Slot) -> None:
    if slot.bookings:  # keep history
        slot.active = False
    else:
        db.session.delete(slot)


def clear_future_schedule(staff, actor, reason: str) -> int:
    """When a staff member is deactivated/demoted: cancel upcoming bookings and retire future slots."""
    slots = (
        db.session.query(Slot)
        .filter(Slot.staff_id == staff.id, Slot.active.is_(True), Slot.start_at > utcnow())
        .all()
    )
    cancelled = 0
    for slot in slots:
        booking = next((b for b in slot.bookings if b.status == CONFIRMED), None)
        if booking:
            cancel_booking(booking, actor, reason)
            cancelled += 1
        _retire_slot(slot)
    db.session.commit()
    return cancelled
