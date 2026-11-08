from flask_login import UserMixin
from sqlalchemy import Index
from werkzeug.security import check_password_hash, generate_password_hash

from .extensions import db, login_manager
from .timeutils import utcnow

SUPERADMIN = "superadmin"
STAFF = "staff"
CUSTOMER = "customer"
ROLES = (SUPERADMIN, STAFF, CUSTOMER)

CONFIRMED = "confirmed"
COMPLETED = "completed"
CANCELLED = "cancelled"


class User(UserMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    name = db.Column(db.String(120), nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), nullable=False, default=CUSTOMER)
    active = db.Column(db.Boolean, nullable=False, default=True)
    failed_logins = db.Column(db.Integer, nullable=False, default=0)
    locked_until = db.Column(db.DateTime, nullable=True)
    reset_requested_at = db.Column(db.DateTime, nullable=True)  # throttles password-reset emails
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)

    @property
    def is_active(self):  # Flask-Login: inactive users cannot log in
        return self.active

    @property
    def is_superadmin(self):
        return self.role == SUPERADMIN

    @property
    def is_staff_like(self):
        return self.role in (STAFF, SUPERADMIN)

    def set_password(self, password: str) -> None:
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)

    def is_locked(self) -> bool:
        return bool(self.locked_until and self.locked_until > utcnow())


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


class Service(db.Model):
    """A type of appointment (replaces the old hardcoded 'General' type)."""

    __tablename__ = "services"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), unique=True, nullable=False)
    description = db.Column(db.String(500), nullable=False, default="")
    duration_minutes = db.Column(db.Integer, nullable=False, default=30)
    use_zoom = db.Column(db.Boolean, nullable=False, default=False)
    active = db.Column(db.Boolean, nullable=False, default=True)


class Slot(db.Model):
    __tablename__ = "slots"

    id = db.Column(db.Integer, primary_key=True)
    staff_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    service_id = db.Column(db.Integer, db.ForeignKey("services.id"), nullable=False)
    start_at = db.Column(db.DateTime, nullable=False)  # naive UTC
    end_at = db.Column(db.DateTime, nullable=False)  # naive UTC
    is_booked = db.Column(db.Boolean, nullable=False, default=False)
    # Soft-delete: slots with booking history are kept (for records) but hidden and unbookable.
    active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)

    staff =db.relationship("User", foreign_keys=[staff_id])
    service = db.relationship("Service")
    bookings = db.relationship("Booking", back_populates="slot")

    __table_args__ = (
        Index("ix_slots_staff_start", "staff_id", "start_at"),
        Index("ix_slots_start_booked", "start_at", "is_booked"),
    )

    @property
    def active_booking(self):
        for booking in self.bookings:
            if booking.status in (CONFIRMED, COMPLETED):
                return booking
        return None


class Booking(db.Model):
    __tablename__ = "bookings"

    id = db.Column(db.Integer, primary_key=True)
    slot_id = db.Column(db.Integer, db.ForeignKey("slots.id"), nullable=False, index=True)
    customer_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    notes = db.Column(db.String(500), nullable=False, default="")
    status = db.Column(db.String(20), nullable=False, default=CONFIRMED)
    zoom_meeting_id = db.Column(db.String(64), nullable=True)
    zoom_link = db.Column(db.String(500), nullable=True)
    cancelled_by_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    cancel_reason = db.Column(db.String(300), nullable=True)
    cancelled_at = db.Column(db.DateTime, nullable=True)
    reminder_sent_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)

    slot = db.relationship("Slot", back_populates="bookings")
    customer = db.relationship("User", foreign_keys=[customer_id])
    cancelled_by = db.relationship("User", foreign_keys=[cancelled_by_id])


class AuditLog(db.Model):
    __tablename__ = "audit_logs"

    id = db.Column(db.Integer, primary_key=True)
    actor_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    action = db.Column(db.String(60), nullable=False)
    detail = db.Column(db.String(500), nullable=False, default="")
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow, index=True)

    actor = db.relationship("User")
