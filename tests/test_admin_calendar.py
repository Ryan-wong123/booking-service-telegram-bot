from app.calendar_util import month_grid
from app.extensions import db
from app.models import CANCELLED, Booking, User
from app.services import booking as svc
from app.timeutils import parse_month, shift_month

from .conftest import PASSWORD, login, make_user


def test_december_calendar_is_correct(app):
    cal = month_grid(2025, 12)
    days = [c["day"] for w in cal["weeks"] for c in w if c]
    assert days == list(range(1, 32))
    assert cal["next"] == "2026-01" and cal["prev"] == "2025-11"
    # 1 Dec 2025 is a Monday -> Sunday-first grid puts it in column index 1
    assert cal["weeks"][0][0] is None and cal["weeks"][0][1]["day"] == 1


def test_calendar_weekday_alignment_matches_real_dates(app):
    import datetime

    for year, month in [(2026, 2), (2026, 11), (2027, 5)]:
        for week in month_grid(year, month)["weeks"]:
            for col, cell in enumerate(week):
                if cell:
                    d = datetime.date(year, month, cell["day"])
                    assert (d.weekday() + 1) % 7 == col  # Sunday=0


def test_month_helpers(app):
    assert shift_month(2026, 12, 1) == (2027, 1)
    assert shift_month(2026, 1, -1) == (2025, 12)
    assert parse_month("garbage") == parse_month(None)  # bad input never crashes


def test_dashboard_bad_month_does_not_crash(client, staff):
    login(client, "staff@example.com")
    assert client.get("/staff/?month=not-a-month&date=zzz").status_code == 200


def test_admin_creates_staff_and_user_can_log_in(client, superadmin):
    login(client, "root@example.com")
    resp = client.post("/admin/users/new", data={"name": "Sam", "email": "sam@example.com", "role": "staff", "password": PASSWORD})
    assert resp.status_code == 302
    client.post("/logout")
    assert login(client, "sam@example.com").headers["Location"].endswith("/staff/")


def test_cannot_demote_or_deactivate_self_or_last_superadmin(client, superadmin):
    login(client, "root@example.com")
    resp = client.post(f"/admin/users/{superadmin.id}", data={"name": "Root", "role": "customer", "active": "on"})
    assert resp.status_code == 400
    resp = client.post(f"/admin/users/{superadmin.id}", data={"name": "Root", "role": "superadmin"})  # unchecked active
    assert resp.status_code == 400
    assert db.session.get(User, superadmin.id).role == "superadmin"


def test_last_superadmin_protected_from_another_superadmin_demotion(client, superadmin):
    second = make_user("second@example.com", "superadmin")
    login(client, "second@example.com")
    # Demoting root is fine while 2 exist...
    assert client.post(f"/admin/users/{superadmin.id}", data={"name": "Root", "role": "staff", "active": "on"}).status_code == 302
    # ...but `second` is now the last one and cannot demote themselves.
    assert client.post(f"/admin/users/{second.id}", data={"name": "S", "role": "staff", "active": "on"}).status_code == 400


def test_deactivating_staff_cancels_their_bookings(client, superadmin, staff, customer, make_slot):
    booking, _ = svc.book_slot(customer, make_slot().id)
    free = make_slot()
    login(client, "root@example.com")
    client.post(f"/admin/users/{staff.id}", data={"name": "Staff", "role": "staff"})  # active unchecked
    assert db.session.get(Booking, booking.id).status == CANCELLED
    assert "no longer available" in db.session.get(Booking, booking.id).cancel_reason
    # slots of a deactivated host can't be booked
    with __import__("pytest").raises(svc.BookingError):
        svc.book_slot(customer, free.id)


def test_customer_sees_staff_cancellation_reason(client, staff, customer, make_slot):
    booking, _ = svc.book_slot(customer, make_slot().id)
    login(client, "staff@example.com")
    assert client.post(f"/staff/bookings/{booking.id}/cancel", data={"reason": ""}).status_code == 400  # reason required
    client.post(f"/staff/bookings/{booking.id}/cancel", data={"reason": "Fire drill"})
    client.post("/logout")
    login(client, "cust@example.com")
    assert b"Fire drill" in client.get("/my-bookings").data


def test_admin_pages_render(client, superadmin, staff, customer, make_slot):
    svc.book_slot(customer, make_slot().id)
    login(client, "root@example.com")
    for url in ("/admin/users", "/admin/users?role=staff", "/admin/users/new", f"/admin/users/{staff.id}",
                "/admin/services", "/admin/services/new", "/admin/bookings", "/admin/bookings?status=confirmed", "/admin/audit"):
        assert client.get(url).status_code == 200, url


def test_staff_and_customer_pages_render(client, staff, customer, make_slot):
    slot = make_slot()
    login(client, "staff@example.com")
    assert client.get("/staff/").status_code == 200
    from app.timeutils import to_local

    d = to_local(slot.start_at)
    assert client.get(f"/staff/?month={d:%Y-%m}&date={d:%Y-%m-%d}").status_code == 200
    client.post("/logout")
    login(client, "cust@example.com")
    assert client.get(f"/slots?month={d:%Y-%m}&date={d:%Y-%m-%d}").status_code == 200
    assert client.get(f"/book/{slot.id}").status_code == 200
    client.post(f"/book/{slot.id}", data={"notes": "hi"})
    assert client.get("/my-bookings").status_code == 200


def test_service_validation(client, superadmin):
    login(client, "root@example.com")
    assert client.post("/admin/services/new", data={"name": "X", "duration_minutes": "1"}).status_code == 400
    assert client.post("/admin/services/new", data={"name": "Consult", "duration_minutes": "45", "active": "on"}).status_code == 302
    assert client.post("/admin/services/new", data={"name": "Consult", "duration_minutes": "45"}).status_code == 400  # duplicate


def test_init_db_cli_bootstraps_superadmin(tmp_path):
    from app import create_app

    app = create_app({"SECRET_KEY": "x", "SQLALCHEMY_DATABASE_URI": f"sqlite:///{tmp_path/'i.db'}",
                      "SUPERADMIN_EMAIL": "boss@example.com", "SUPERADMIN_PASSWORD": "a-long-password-1"})
    runner = app.test_cli_runner()
    assert runner.invoke(args=["init-db"]).exit_code == 0
    assert runner.invoke(args=["init-db"]).exit_code == 0  # idempotent
    with app.app_context():
        assert User.query.filter_by(role="superadmin").count() == 1
