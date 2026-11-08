from datetime import timedelta

from app.extensions import db
from app.models import Booking
from app.services import booking as svc
from app.services import notifications
from app.timeutils import utcnow

from .conftest import login


def outbox(app):
    return app.extensions.setdefault("outbox", [])


def to_addrs(app):
    return sorted(m["To"] for m in outbox(app))


def test_booking_emails_customer_and_staff(app, customer, staff, make_slot):
    svc.book_slot(customer, make_slot().id, "please be gentle")
    assert to_addrs(app) == ["cust@example.com", "staff@example.com"]
    staff_mail = next(m for m in outbox(app) if m["To"] == "staff@example.com")
    assert "please be gentle" in staff_mail.get_content()
    assert "/my-bookings" in next(m for m in outbox(app) if m["To"] == "cust@example.com").get_content()


def test_cancel_notifies_the_other_party_only(app, customer, staff, make_slot):
    booking, _ = svc.book_slot(customer, make_slot().id)
    outbox(app).clear()
    svc.cancel_booking(booking, customer, "busy")  # customer cancels -> only staff hears
    assert to_addrs(app) == ["staff@example.com"]
    booking2, _ = svc.book_slot(customer, make_slot().id)
    outbox(app).clear()
    svc.cancel_booking(booking2, staff, "sick")  # staff cancels -> customer hears, with reason
    assert to_addrs(app) == ["cust@example.com"]
    assert "sick" in outbox(app)[0].get_content()


def test_admin_cancel_notifies_both(app, superadmin, customer, staff, make_slot):
    booking, _ = svc.book_slot(customer, make_slot().id)
    outbox(app).clear()
    svc.cancel_booking(booking, superadmin, "policy")
    assert to_addrs(app) == ["cust@example.com", "staff@example.com"]


def test_reschedule_notifies(app, customer, staff, make_slot):
    booking, _ = svc.book_slot(customer, make_slot().id)
    new = make_slot()
    outbox(app).clear()
    svc.reschedule_booking(booking, new.id, customer)
    assert "cust@example.com" in to_addrs(app) and "staff@example.com" in to_addrs(app)


def test_email_failure_never_breaks_booking(app, customer, make_slot, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("smtp down")

    monkeypatch.setattr(notifications, "send_email", boom)
    booking, _ = svc.book_slot(customer, make_slot().id)
    assert booking.status == "confirmed"


def test_reminders_sent_once_inside_window(app, customer, make_slot):
    far = make_slot(hours_ahead=24 * 5)  # outside the 24h window
    soon = make_slot(hours_ahead=0)  # created inside the window...
    b_far, _ = svc.book_slot(customer, far.id)
    b_soon, _ = svc.book_slot(customer, soon.id)
    assert b_soon.reminder_sent_at is not None  # ...so the confirmation counts as the reminder
    assert b_far.reminder_sent_at is None
    outbox(app).clear()
    assert notifications.send_due_reminders() == 0  # nothing due yet

    b_far.slot.start_at = utcnow() + timedelta(hours=10)
    b_far.slot.end_at = b_far.slot.start_at + timedelta(minutes=30)
    db.session.commit()
    assert notifications.send_due_reminders() == 1
    assert [m["To"] for m in outbox(app)] == ["cust@example.com"]
    assert notifications.send_due_reminders() == 0  # idempotent: no duplicate reminder


def test_reminder_skips_cancelled(app, customer, make_slot):
    booking, _ = svc.book_slot(customer, make_slot(hours_ahead=24 * 5).id)
    svc.cancel_booking(booking, customer)
    booking.slot.start_at = utcnow() + timedelta(hours=5)
    db.session.commit()
    outbox(app).clear()
    assert notifications.send_due_reminders() == 0


def test_failed_reminder_is_retried(app, customer, make_slot, monkeypatch):
    booking, _ = svc.book_slot(customer, make_slot(hours_ahead=24 * 5).id)
    booking.slot.start_at = utcnow() + timedelta(hours=5)
    db.session.commit()
    monkeypatch.setattr(notifications, "send_email", lambda *a, **k: False)  # SMTP failure
    assert notifications.send_due_reminders() == 0
    assert db.session.get(Booking, booking.id).reminder_sent_at is None
    monkeypatch.undo()
    assert notifications.send_due_reminders() == 1


def test_reschedule_resets_reminder(app, customer, make_slot):
    booking, _ = svc.book_slot(customer, make_slot(hours_ahead=24 * 5).id)
    booking.reminder_sent_at = utcnow()
    db.session.commit()
    svc.reschedule_booking(booking, make_slot(hours_ahead=24 * 6).id, customer)
    assert booking.reminder_sent_at is None


def test_send_reminders_cli(app, customer, make_slot):
    booking, _ = svc.book_slot(customer, make_slot(hours_ahead=24 * 5).id)
    booking.slot.start_at = utcnow() + timedelta(hours=5)
    db.session.commit()
    result = app.test_cli_runner().invoke(args=["send-reminders"])
    assert result.exit_code == 0 and "Sent 1 reminder" in result.output


# ---- password reset ----
def reset_link(app):
    import re

    body = outbox(app)[-1].get_content()
    return re.search(r"http://localhost:8000(/reset-password/\S+)", body).group(1)


def test_forgot_password_flow(app, client, customer):
    resp = client.post("/forgot-password", data={"email": "cust@example.com"})
    assert resp.status_code == 302
    path = reset_link(app)
    assert client.get(path).status_code == 200
    new = "a-brand-new-password"
    assert client.post(path, data={"password": new, "confirm": new}).status_code == 302
    assert login(client, "cust@example.com", new).status_code == 302  # new password works
    client.post("/logout")
    assert login(client, "cust@example.com").status_code == 401  # old one doesn't


def test_reset_link_is_single_use(app, client, customer):
    client.post("/forgot-password", data={"email": "cust@example.com"})
    path = reset_link(app)
    new = "a-brand-new-password"
    client.post(path, data={"password": new, "confirm": new})
    assert client.get(path).status_code == 302  # token no longer valid


def test_reset_link_expires(app, client, customer):
    client.post("/forgot-password", data={"email": "cust@example.com"})
    path = reset_link(app)
    app.config["RESET_TOKEN_MINUTES"] = 0
    import time

    time.sleep(1.1)
    assert client.get(path).status_code == 302


def test_reset_tampered_token_rejected(app, client, customer):
    client.post("/forgot-password", data={"email": "cust@example.com"})
    assert client.get(reset_link(app) + "x").status_code == 302


def test_forgot_password_does_not_reveal_accounts(app, client, customer):
    known = client.post("/forgot-password", data={"email": "cust@example.com"}, follow_redirects=True).data
    outbox(app).clear()
    unknown = client.post("/forgot-password", data={"email": "nobody@example.com"}, follow_redirects=True).data
    assert outbox(app) == []  # nothing sent...
    assert b"sent a link" in known and b"sent a link" in unknown  # ...but identical response


def test_forgot_password_is_throttled(app, client, customer):
    client.post("/forgot-password", data={"email": "cust@example.com"})
    client.post("/forgot-password", data={"email": "cust@example.com"})
    assert len(outbox(app)) == 1


def test_reset_unlocks_locked_account(app, client, customer):
    for _ in range(3):
        login(client, "cust@example.com", "wrong-password")
    client.post("/forgot-password", data={"email": "cust@example.com"})
    new = "a-brand-new-password"
    client.post(reset_link(app), data={"password": new, "confirm": new})
    assert login(client, "cust@example.com", new).status_code == 302


def test_reset_enforces_password_policy(app, client, customer):
    client.post("/forgot-password", data={"email": "cust@example.com"})
    assert client.post(reset_link(app), data={"password": "short", "confirm": "short"}).status_code == 400


def test_change_password_requires_current(app, client, customer):
    login(client, "cust@example.com")
    bad = client.post("/account", data={"current": "nope", "password": "another-long-password", "confirm": "another-long-password"})
    assert bad.status_code == 400
    ok = client.post("/account", data={"current": "correct-horse-battery", "password": "another-long-password", "confirm": "another-long-password"})
    assert ok.status_code == 302
    client.post("/logout")
    assert login(client, "cust@example.com", "another-long-password").status_code == 302
