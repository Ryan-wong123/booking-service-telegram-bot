from collections import defaultdict
from datetime import datetime

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user

from ..calendar_util import month_grid
from ..extensions import db
from ..models import STAFF, SUPERADMIN, Booking, Service, Slot
from ..security import roles_required
from ..services import booking as svc
from ..timeutils import local_to_utc, month_bounds_utc, parse_date, parse_month, to_local, utcnow

bp = Blueprint("staff", __name__, url_prefix="/staff")


def _status(total: int, booked: int) -> str:
    if booked == 0:
        return "free"
    return "full" if booked == total else "partial"


@bp.get("/")
@roles_required(STAFF, SUPERADMIN)
def dashboard():
    year, month = parse_month(request.args.get("month"))
    selected = parse_date(request.args.get("date"))
    start, end = month_bounds_utc(year, month)

    slots = (
        Slot.query.filter(
            Slot.staff_id == current_user.id,
            Slot.active.is_(True),
            Slot.start_at >= start,
            Slot.start_at < end,
        )
        .order_by(Slot.start_at)
        .all()
    )
    by_date = defaultdict(list)
    for slot in slots:
        by_date[to_local(slot.start_at).date().isoformat()].append(slot)

    day_info = {
        d: {"total": len(items), "status": _status(len(items), sum(1 for s in items if s.is_booked))}
        for d, items in by_date.items()
    }
    selected_key = selected.isoformat() if selected else None
    visible = {selected_key: by_date.get(selected_key, [])} if selected_key else dict(by_date)
    return render_template(
        "staff/dashboard.html",
        cal=month_grid(year, month, day_info),
        groups=visible,
        selected=selected_key,
        services=Service.query.filter_by(active=True).order_by(Service.name).all(),
        now=utcnow(),
    )


@bp.post("/slots")
@roles_required(STAFF, SUPERADMIN)
def create_slots():
    month = request.form.get("month", "")
    try:
        service = db.session.get(Service, request.form.get("service_id", type=int))
        if not service:
            raise svc.BookingError("Choose a service.")
        d = datetime.strptime(request.form.get("date", ""), "%Y-%m-%d").date()
        t = datetime.strptime(request.form.get("time", ""), "%H:%M").time()
        count = request.form.get("count", 1, type=int)
        slots = svc.create_slots(current_user, service, local_to_utc(d, t), count)
        flash(f"Created {len(slots)} slot(s).", "success")
        month = d.strftime("%Y-%m")
    except ValueError:
        flash("Enter a valid date and time.", "danger")
    except svc.BookingError as exc:
        flash(str(exc), "danger")
    return redirect(url_for("staff.dashboard", month=month or None))


def _own_slot_or_404(slot_id) -> Slot:
    slot = db.session.get(Slot, slot_id)
    if not slot or not slot.active or slot.staff_id != current_user.id:
        abort(404)
    return slot


@bp.post("/slots/<int:slot_id>/delete")
@roles_required(STAFF, SUPERADMIN)
def delete_slot(slot_id):
    slot = _own_slot_or_404(slot_id)
    date_key = to_local(slot.start_at).strftime("%Y-%m-%d")
    try:
        svc.delete_slot(slot, current_user)
        flash("Slot removed.", "success")
    except svc.BookingError as exc:
        flash(str(exc), "danger")
    return redirect(url_for("staff.dashboard", month=date_key[:7], date=date_key))


def _booking_for_staff_or_404(booking_id) -> Booking:
    booking = db.session.get(Booking, booking_id)
    if not booking or booking.slot.staff_id != current_user.id:
        abort(404)
    return booking


@bp.route("/bookings/<int:booking_id>/cancel", methods=["GET", "POST"])
@roles_required(STAFF, SUPERADMIN)
def cancel_booking(booking_id):
    booking = _booking_for_staff_or_404(booking_id)
    if request.method == "POST":
        reason = request.form.get("reason", "").strip()
        if not reason:
            flash("Please give the customer a reason.", "danger")
            return render_template("staff/cancel.html", booking=booking), 400
        try:
            svc.cancel_booking(booking, current_user, reason)
            flash("Booking cancelled. The customer will see your reason.", "success")
        except svc.BookingError as exc:
            flash(str(exc), "danger")
        date_key = to_local(booking.slot.start_at).strftime("%Y-%m-%d")
        return redirect(url_for("staff.dashboard", month=date_key[:7], date=date_key))
    return render_template("staff/cancel.html", booking=booking)


@bp.post("/bookings/<int:booking_id>/complete")
@roles_required(STAFF, SUPERADMIN)
def complete_booking(booking_id):
    booking = _booking_for_staff_or_404(booking_id)
    try:
        svc.complete_booking(booking, current_user)
        flash("Marked as completed.", "success")
    except svc.BookingError as exc:
        flash(str(exc), "danger")
    date_key = to_local(booking.slot.start_at).strftime("%Y-%m-%d")
    return redirect(url_for("staff.dashboard", month=date_key[:7], date=date_key))
