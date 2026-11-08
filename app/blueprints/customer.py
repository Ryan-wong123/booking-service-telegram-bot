from collections import defaultdict

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user

from ..calendar_util import month_grid
from ..extensions import db
from ..models import CONFIRMED, CUSTOMER, Booking, Service, Slot, User
from ..security import roles_required
from ..services import booking as svc
from ..timeutils import month_bounds_utc, parse_date, parse_month, to_local, utcnow

bp = Blueprint("customer", __name__)


def _free_slots(start, end, service_id=None):
    query = (
        Slot.query.join(Service, Slot.service_id == Service.id)
        .join(User, Slot.staff_id == User.id)
        .filter(
            Slot.active.is_(True),
            Slot.is_booked.is_(False),
            Slot.start_at > utcnow(),
            Slot.start_at >= start,
            Slot.start_at < end,
            Service.active.is_(True),
            User.active.is_(True),
        )
        .order_by(Slot.start_at)
    )
    if service_id:
        query = query.filter(Slot.service_id == service_id)
    return query.all()


def _group_by_date(slots):
    groups = defaultdict(list)
    for slot in slots:
        groups[to_local(slot.start_at).date().isoformat()].append(slot)
    return dict(groups)


@bp.get("/slots")
@roles_required(CUSTOMER)
def slots():
    year, month = parse_month(request.args.get("month"))
    service_id = request.args.get("service", type=int)
    selected = parse_date(request.args.get("date"))
    start, end = month_bounds_utc(year, month)

    grouped = _group_by_date(_free_slots(start, end, service_id))
    day_info = {d: {"free": len(items)} for d, items in grouped.items()}
    selected_key = selected.isoformat() if selected else None
    visible = {selected_key: grouped.get(selected_key, [])} if selected_key else grouped

    return render_template(
        "customer/slots.html",
        cal=month_grid(year, month, day_info),
        groups=visible,
        selected=selected_key,
        services=Service.query.filter_by(active=True).order_by(Service.name).all(),
        service_id=service_id,
    )


@bp.route("/book/<int:slot_id>", methods=["GET", "POST"])
@roles_required(CUSTOMER)
def book(slot_id):
    slot = db.session.get(Slot, slot_id)
    if not slot or not slot.active or slot.is_booked or slot.start_at <= utcnow():
        flash("That slot is no longer available.", "warning")
        return redirect(url_for("customer.slots"))
    if request.method == "POST":
        try:
            booking, zoom_ok = svc.book_slot(current_user, slot_id, request.form.get("notes", ""))
        except svc.BookingError as exc:
            flash(str(exc), "danger")
            return redirect(url_for("customer.slots"))
        flash("Your appointment is booked.", "success")
        if not zoom_ok:
            flash("We couldn't create the Zoom link automatically; your host will share one with you.", "warning")
        return redirect(url_for("customer.my_bookings"))
    return render_template("customer/book.html", slot=slot)


@bp.get("/my-bookings")
@roles_required(CUSTOMER)
def my_bookings():
    now = utcnow()
    rows = (
        Booking.query.join(Slot, Booking.slot_id == Slot.id)
        .filter(Booking.customer_id == current_user.id)
        .order_by(Slot.start_at.desc())
        .all()
    )
    upcoming = sorted(
        [b for b in rows if b.status == CONFIRMED and b.slot.start_at > now], key=lambda b: b.slot.start_at
    )
    past = [b for b in rows if b not in upcoming]
    return render_template("customer/my_bookings.html", upcoming=upcoming, past=past, now=now)


def _own_booking_or_404(booking_id) -> Booking:
    booking = db.session.get(Booking, booking_id)
    # Ownership check: another customer's id looks exactly like a missing one.
    if not booking or booking.customer_id != current_user.id:
        abort(404)
    return booking


@bp.route("/bookings/<int:booking_id>/cancel", methods=["GET", "POST"])
@roles_required(CUSTOMER)
def cancel(booking_id):
    booking = _own_booking_or_404(booking_id)
    if request.method == "POST":
        try:
            svc.cancel_booking(booking, current_user, request.form.get("reason", ""))
            flash("Your booking has been cancelled.", "success")
        except svc.BookingError as exc:
            flash(str(exc), "danger")
        return redirect(url_for("customer.my_bookings"))
    return render_template("customer/cancel.html", booking=booking)


@bp.route("/bookings/<int:booking_id>/reschedule", methods=["GET", "POST"])
@roles_required(CUSTOMER)
def reschedule(booking_id):
    booking = _own_booking_or_404(booking_id)
    if booking.status != CONFIRMED or booking.slot.start_at <= utcnow():
        flash("Only upcoming bookings can be rescheduled.", "warning")
        return redirect(url_for("customer.my_bookings"))
    if request.method == "POST":
        try:
            zoom_ok = svc.reschedule_booking(booking, request.form.get("slot_id", type=int), current_user)
            flash("Your booking has been moved.", "success")
            if not zoom_ok:
                flash("We couldn't create a new Zoom link automatically; your host will share one.", "warning")
        except svc.BookingError as exc:
            flash(str(exc), "danger")
            return redirect(url_for("customer.reschedule", booking_id=booking.id))
        return redirect(url_for("customer.my_bookings"))

    year, month = parse_month(request.args.get("month"))
    start, end = month_bounds_utc(year, month)
    grouped = _group_by_date(_free_slots(start, end, booking.slot.service_id))
    cal = month_grid(year, month)
    return render_template("customer/reschedule.html", booking=booking, groups=grouped, cal=cal)
