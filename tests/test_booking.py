from datetime import timedelta

import pytest

from app.extensions import db
from app.models import CANCELLED, COMPLETED, CONFIRMED, Booking, Slot
from app.services import booking as svc
from app.timeutils import utcnow

from .conftest import login


def test_book_marks_slot_booked(app, customer, make_slot):
    slot = make_slot()
    booking, zoom_ok = svc.book_slot(customer, slot.id, "hello")
    assert zoom_ok and booking.status == CONFIRMED
    assert db.session.get(Slot, slot.id).is_booked


def test_second_customer_cannot_take_booked_slot(app, customer, customer2, make_slot):
    slot = make_slot()
    svc.book_slot(customer, slot.id)
    with pytest.raises(svc.BookingError):
        svc.book_slot(customer2, slot.id)
    assert Booking.query.count() == 1


def test_claim_is_atomic(app, customer, make_slot):
    """The conditional UPDATE lets exactly one claim win, which is what prevents double booking."""
    slot = make_slot()
    assert svc._claim_slot(slot.id) is True
    assert svc._claim_slot(slot.id) is False


def test_cannot_book_past_slot(app, customer, make_slot):
    slot = make_slot(hours_ahead=-100)
    with pytest.raises(svc.BookingError):
        svc.book_slot(customer, slot.id)


def test_booking_limit(app, customer, make_slot):
    for _ in range(2):
        svc.book_slot(customer, make_slot().id)
    with pytest.raises(svc.BookingError, match="at most 2"):
        svc.book_slot(customer, make_slot().id)


def test_customer_overlap_rejected(app, customer, staff, make_slot):
    a = make_slot()
    svc.book_slot(customer, a.id)
    overlapping = Slot(staff_id=staff.id, service_id=a.service_id, start_at=a.start_at + timedelta(minutes=10),
                       end_at=a.end_at + timedelta(minutes=10))
    db.session.add(overlapping)
    db.session.commit()
    with pytest.raises(svc.BookingError, match="overlaps"):
        svc.book_slot(customer, overlapping.id)


def test_cancel_frees_slot_and_records_actor(app, customer, staff, make_slot):
    slot = make_slot()
    booking, _ = svc.book_slot(customer, slot.id)
    svc.cancel_booking(booking, staff, "Sick")
    assert booking.status == CANCELLED and booking.cancel_reason == "Sick" and booking.cancelled_by_id == staff.id
    assert not db.session.get(Slot, slot.id).is_booked
    svc.book_slot(customer, slot.id)  # bookable again


def test_customer_cannot_cancel_other_customers_booking(app, client, customer, customer2, make_slot):
    booking, _ = svc.book_slot(customer, make_slot().id)
    login(client, "cust2@example.com")
    assert client.get(f"/bookings/{booking.id}/cancel").status_code == 404
    assert client.post(f"/bookings/{booking.id}/cancel").status_code == 404
    assert db.session.get(Booking, booking.id).status == CONFIRMED


def test_customer_cancel_via_web(app, client, customer, make_slot):
    booking, _ = svc.book_slot(customer, make_slot().id)
    login(client, "cust@example.com")
    assert client.get(f"/bookings/{booking.id}/cancel").status_code == 200  # confirmation page
    client.post(f"/bookings/{booking.id}/cancel", data={"reason": "plans changed"})
    assert db.session.get(Booking, booking.id).status == CANCELLED


def test_reschedule_moves_booking_and_swaps_slots(app, customer, make_slot):
    old, new = make_slot(), make_slot()
    booking, _ = svc.book_slot(customer, old.id)
    svc.reschedule_booking(booking, new.id, customer)
    assert booking.slot_id == new.id
    assert db.session.get(Slot, new.id).is_booked and not db.session.get(Slot, old.id).is_booked


def test_reschedule_to_taken_slot_fails_and_keeps_original(app, customer, customer2, make_slot):
    old, taken = make_slot(), make_slot()
    booking, _ = svc.book_slot(customer, old.id)
    svc.book_slot(customer2, taken.id)
    with pytest.raises(svc.BookingError):
        svc.reschedule_booking(booking, taken.id, customer)
    assert booking.slot_id == old.id and db.session.get(Slot, old.id).is_booked


def test_complete_requires_started(app, customer, staff, make_slot):
    booking, _ = svc.book_slot(customer, make_slot().id)
    with pytest.raises(svc.BookingError):
        svc.complete_booking(booking, staff)
    booking.slot.start_at = utcnow() - timedelta(hours=1)
    db.session.commit()
    svc.complete_booking(booking, staff)
    assert booking.status == COMPLETED


def test_create_slots_validation(app, staff):
    from app.models import Service

    service = Service.query.first()
    with pytest.raises(svc.BookingError, match="future"):
        svc.create_slots(staff, service, utcnow() - timedelta(hours=1), 1)
    start = utcnow() + timedelta(days=3)
    slots = svc.create_slots(staff, service, start, 3)
    assert [s.end_at for s in slots[:-1]] == [s.start_at for s in slots[1:]]  # back to back
    with pytest.raises(svc.BookingError, match="overlaps"):
        svc.create_slots(staff, service, start + timedelta(minutes=15), 1)
    with pytest.raises(svc.BookingError):
        svc.create_slots(staff, service, start + timedelta(days=1), 21)


def test_delete_booked_slot_refused_but_history_kept(app, customer, staff, make_slot):
    slot = make_slot()
    booking, _ = svc.book_slot(customer, slot.id)
    with pytest.raises(svc.BookingError):
        svc.delete_slot(slot, staff)
    svc.cancel_booking(booking, customer)
    svc.delete_slot(slot, staff)  # soft-deleted: cancelled booking still references it
    assert db.session.get(Slot, slot.id).active is False
    with pytest.raises(svc.BookingError):
        svc.book_slot(customer, slot.id)


def test_staff_can_only_touch_own_slots(app, client, staff, customer, make_slot):
    from .conftest import make_user

    other = make_user("other@example.com", "staff")
    slot = make_slot(staff_user=other)
    login(client, "staff@example.com")
    assert client.post(f"/staff/slots/{slot.id}/delete").status_code == 404


def test_zoom_failure_does_not_break_booking(app, customer, make_slot, monkeypatch):
    from app.models import Service
    from app.services import zoom

    Service.query.first().use_zoom = True
    db.session.commit()
    monkeypatch.setattr(zoom, "enabled", lambda: True)
    monkeypatch.setattr(zoom, "create_meeting", lambda *a, **k: None)  # simulated outage
    booking, zoom_ok = svc.book_slot(customer, make_slot().id)
    assert booking.status == CONFIRMED and zoom_ok is False and booking.zoom_link is None


def test_zoom_link_saved_and_deleted_on_cancel(app, customer, make_slot, monkeypatch):
    from app.models import Service
    from app.services import zoom

    Service.query.first().use_zoom = True
    db.session.commit()
    deleted = []
    monkeypatch.setattr(zoom, "enabled", lambda: True)
    monkeypatch.setattr(zoom, "create_meeting", lambda *a, **k: ("123", "https://zoom.example/j/123"))
    monkeypatch.setattr(zoom, "delete_meeting", lambda mid: deleted.append(mid))
    booking, _ = svc.book_slot(customer, make_slot().id)
    assert booking.zoom_link == "https://zoom.example/j/123"
    svc.cancel_booking(booking, customer)
    assert deleted == ["123"]
