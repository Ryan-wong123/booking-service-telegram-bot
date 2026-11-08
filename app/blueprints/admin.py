from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user

from ..extensions import db
from ..models import ROLES, STAFF, SUPERADMIN, AuditLog, Booking, Service, Slot, User
from ..security import audit, roles_required
from ..services import booking as svc
from ..timeutils import utcnow
from .auth import EMAIL_RE, validate_password

bp = Blueprint("admin", __name__, url_prefix="/admin")

PAGE_SIZE = 25


def _superadmin_count() -> int:
    return User.query.filter_by(role=SUPERADMIN, active=True).count()


# ---------- users ----------
@bp.get("/users")
@roles_required(SUPERADMIN)
def users():
    role = request.args.get("role")
    query = db.select(User).order_by(User.role, User.name)
    if role in ROLES:
        query = query.where(User.role == role)
    page = db.paginate(query, per_page=PAGE_SIZE, error_out=False)
    return render_template("admin/users.html", page=page, role=role, roles=ROLES)


@bp.route("/users/new", methods=["GET", "POST"])
@roles_required(SUPERADMIN)
def user_new():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        role = request.form.get("role")
        password = request.form.get("password", "")
        error = None
        if not name or len(name) > 120:
            error = "Enter a name."
        elif not EMAIL_RE.match(email):
            error = "Enter a valid email."
        elif role not in ROLES:
            error = "Choose a role."
        else:
            error = validate_password(password)
        if not error and User.query.filter_by(email=email).first():
            error = "That email is already registered."
        if error:
            flash(error, "danger")
            return render_template("admin/user_form.html", user=None, roles=ROLES, form=request.form), 400
        user = User(name=name, email=email, role=role)
        user.set_password(password)
        db.session.add(user)
        audit("user.create", f"email={email} role={role}", current_user)
        db.session.commit()
        flash(f"Created {role} account for {email}.", "success")
        return redirect(url_for("admin.users"))
    return render_template("admin/user_form.html", user=None, roles=ROLES, form={})


@bp.route("/users/<int:user_id>", methods=["GET", "POST"])
@roles_required(SUPERADMIN)
def user_edit(user_id):
    user = db.session.get(User, user_id) or abort(404)
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        role = request.form.get("role", user.role)
        active = request.form.get("active") == "on"
        password = request.form.get("password", "")
        error = None
        if not name:
            error = "Enter a name."
        elif role not in ROLES:
            error = "Choose a role."
        elif password and validate_password(password):
            error = validate_password(password)
        elif user.id == current_user.id and (role != user.role or not active):
            error = "You cannot change your own role or deactivate yourself."
        elif user.role == SUPERADMIN and (role != SUPERADMIN or not active) and _superadmin_count() <= 1:
            error = "At least one active super admin must remain."
        if error:
            flash(error, "danger")
            return render_template("admin/user_form.html", user=user, roles=ROLES, form=request.form), 400

        was_staff_like = user.role in (STAFF, SUPERADMIN) and user.active
        user.name, user.role, user.active = name, role, active
        if password:
            user.set_password(password)
            user.failed_logins, user.locked_until = 0, None
        audit("user.update", f"user={user.id} role={role} active={active}", current_user)
        db.session.commit()
        if was_staff_like and (not active or role not in (STAFF, SUPERADMIN)):
            cancelled = svc.clear_future_schedule(user, current_user, "Your host is no longer available.")
            if cancelled:
                flash(f"{cancelled} upcoming booking(s) were cancelled and customers notified in their account.", "warning")
        flash("User updated.", "success")
        return redirect(url_for("admin.users"))
    return render_template("admin/user_form.html", user=user, roles=ROLES, form={})


@bp.post("/users/<int:user_id>/unlock")
@roles_required(SUPERADMIN)
def user_unlock(user_id):
    user = db.session.get(User, user_id) or abort(404)
    user.failed_logins, user.locked_until = 0, None
    audit("user.unlock", f"user={user.id}", current_user)
    db.session.commit()
    flash("Account unlocked.", "success")
    return redirect(url_for("admin.users"))


# ---------- services ----------
@bp.get("/services")
@roles_required(SUPERADMIN)
def services():
    return render_template("admin/services.html", services=Service.query.order_by(Service.name).all())


@bp.route("/services/new", methods=["GET", "POST"])
@bp.route("/services/<int:service_id>", methods=["GET", "POST"])
@roles_required(SUPERADMIN)
def service_edit(service_id=None):
    service = (db.session.get(Service, service_id) or abort(404)) if service_id else None
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        description = request.form.get("description", "").strip()[:500]
        duration = request.form.get("duration_minutes", type=int)
        error = None
        if not name or len(name) > 120:
            error = "Enter a service name."
        elif not duration or not 5 <= duration <= 480:
            error = "Duration must be between 5 and 480 minutes."
        else:
            clash = Service.query.filter(Service.name == name)
            if service:
                clash = clash.filter(Service.id != service.id)
            if clash.first():
                error = "A service with that name already exists."
        if error:
            flash(error, "danger")
            return render_template("admin/service_form.html", service=service, form=request.form), 400
        if not service:
            service = Service()
            db.session.add(service)
        service.name, service.description, service.duration_minutes = name, description, duration
        service.use_zoom = request.form.get("use_zoom") == "on"
        service.active = request.form.get("active", "on" if not service_id else "") == "on"
        audit("service.save", f"name={name}", current_user)
        db.session.commit()
        flash("Service saved.", "success")
        return redirect(url_for("admin.services"))
    return render_template("admin/service_form.html", service=service, form={})


# ---------- bookings & audit ----------
@bp.get("/bookings")
@roles_required(SUPERADMIN)
def bookings():
    status = request.args.get("status")
    query = db.select(Booking).join(Slot, Booking.slot_id == Slot.id).order_by(Slot.start_at.desc())
    if status in ("confirmed", "completed", "cancelled"):
        query = query.where(Booking.status == status)
    page = db.paginate(query, per_page=PAGE_SIZE, error_out=False)
    return render_template("admin/bookings.html", page=page, status=status, now=utcnow())


@bp.route("/bookings/<int:booking_id>/cancel", methods=["GET", "POST"])
@roles_required(SUPERADMIN)
def booking_cancel(booking_id):
    booking = db.session.get(Booking, booking_id) or abort(404)
    if request.method == "POST":
        reason = request.form.get("reason", "").strip()
        if not reason:
            flash("Please give the customer a reason.", "danger")
            return render_template("staff/cancel.html", booking=booking, post_url=url_for("admin.booking_cancel", booking_id=booking.id)), 400
        try:
            svc.cancel_booking(booking, current_user, reason)
            flash("Booking cancelled.", "success")
        except svc.BookingError as exc:
            flash(str(exc), "danger")
        return redirect(url_for("admin.bookings"))
    return render_template("staff/cancel.html", booking=booking, post_url=url_for("admin.booking_cancel", booking_id=booking.id))


@bp.get("/audit")
@roles_required(SUPERADMIN)
def audit_log():
    page = db.paginate(db.select(AuditLog).order_by(AuditLog.created_at.desc()), per_page=50, error_out=False)
    return render_template("admin/audit.html", page=page)
