import re
from datetime import timedelta

from flask import Blueprint, current_app, flash, redirect, render_template, request, session, url_for
from flask_login import current_user, login_required, login_user, logout_user
from werkzeug.security import check_password_hash, generate_password_hash

from .. import role_home
from ..extensions import db
from ..models import CUSTOMER, User
from ..security import audit, is_safe_next, load_reset_token, make_reset_token
from ..services import notifications
from ..timeutils import utcnow

bp = Blueprint("auth", __name__)

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
# Hash checked when the email is unknown, so timing doesn't reveal which emails exist.
_DUMMY_HASH = generate_password_hash("not-a-real-password")


def validate_password(password: str) -> str | None:
    minimum = current_app.config["MIN_PASSWORD_LENGTH"]
    if len(password) < minimum:
        return f"Password must be at least {minimum} characters."
    return None


@bp.get("/")
def index():
    if current_user.is_authenticated:
        return redirect(role_home(current_user))
    return redirect(url_for("auth.login"))


@bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(role_home(current_user))
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        user = User.query.filter_by(email=email).first()

        if user and user.is_locked():
            flash("Too many failed attempts. Try again later.", "danger")
            return render_template("auth/login.html"), 429

        if not user:
            check_password_hash(_DUMMY_HASH, password)
        if user and user.active and user.check_password(password):
            user.failed_logins, user.locked_until = 0, None
            audit("auth.login", f"user={user.id}", user)
            db.session.commit()
            login_user(user)
            session.permanent = True
            target = request.args.get("next")
            return redirect(target if is_safe_next(target) else role_home(user))

        if user:
            user.failed_logins += 1
            if user.failed_logins >= current_app.config["LOCKOUT_ATTEMPTS"]:
                user.locked_until = utcnow() + timedelta(minutes=current_app.config["LOCKOUT_MINUTES"])
                user.failed_logins = 0
                audit("auth.lockout", f"user={user.id}")
            db.session.commit()
        flash("Invalid email or password.", "danger")  # same message for every failure
        return render_template("auth/login.html"), 401
    return render_template("auth/login.html")


@bp.post("/logout")
@login_required
def logout():
    logout_user()
    flash("You have been logged out.", "info")
    return redirect(url_for("auth.login"))


@bp.route("/register", methods=["GET", "POST"])
def register():
    if not current_app.config["ALLOW_REGISTRATION"]:
        flash("Registration is closed. Please contact the administrator.", "warning")
        return redirect(url_for("auth.login"))
    if current_user.is_authenticated:
        return redirect(role_home(current_user))
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        error = None
        if not name or len(name) > 120:
            error = "Please enter your name."
        elif not EMAIL_RE.match(email) or len(email) > 255:
            error = "Please enter a valid email address."
        elif password != request.form.get("confirm", ""):
            error = "Passwords do not match."
        else:
            error = validate_password(password)
        if not error and User.query.filter_by(email=email).first():
            error = "That email is already registered."
        if error:
            flash(error, "danger")
            return render_template("auth/register.html", name=name, email=email), 400
        user = User(email=email, name=name, role=CUSTOMER)
        user.set_password(password)
        db.session.add(user)
        audit("auth.register", f"email={email}", user)
        db.session.commit()
        login_user(user)
        session.permanent = True
        flash("Welcome! Your account has been created.", "success")
        return redirect(role_home(user))
    return render_template("auth/register.html")


RESET_THROTTLE = timedelta(minutes=2)


@bp.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        user = User.query.filter_by(email=email).first()
        now = utcnow()
        if user and user.active and not (user.reset_requested_at and now - user.reset_requested_at < RESET_THROTTLE):
            user.reset_requested_at = now
            audit("auth.reset_requested", f"user={user.id}")
            db.session.commit()
            url = current_app.config["APP_BASE_URL"].rstrip("/") + url_for("auth.reset_password", token=make_reset_token(user))
            notifications.password_reset(user, url, current_app.config["RESET_TOKEN_MINUTES"])
        # Same answer whether or not the account exists (no account enumeration).
        flash("If that email has an account, we've sent a link to reset the password.", "info")
        return redirect(url_for("auth.login"))
    return render_template("auth/forgot.html")


@bp.route("/reset-password/<token>", methods=["GET", "POST"])
def reset_password(token):
    user = load_reset_token(token)
    if not user:
        flash("That reset link is invalid or has expired. Please request a new one.", "danger")
        return redirect(url_for("auth.forgot_password"))
    if request.method == "POST":
        password = request.form.get("password", "")
        error = validate_password(password)
        if not error and password != request.form.get("confirm", ""):
            error = "Passwords do not match."
        if error:
            flash(error, "danger")
            return render_template("auth/reset.html", token=token), 400
        user.set_password(password)
        user.failed_logins, user.locked_until = 0, None
        audit("auth.reset_done", f"user={user.id}", user)
        db.session.commit()
        flash("Your password has been changed. Please log in.", "success")
        return redirect(url_for("auth.login"))
    return render_template("auth/reset.html", token=token)


@bp.route("/account", methods=["GET", "POST"])
@login_required
def account():
    if request.method == "POST":
        new = request.form.get("password", "")
        error = None
        if not current_user.check_password(request.form.get("current", "")):
            error = "Your current password is incorrect."
        elif new != request.form.get("confirm", ""):
            error = "New passwords do not match."
        else:
            error = validate_password(new)
        if error:
            flash(error, "danger")
            return render_template("auth/account.html"), 400
        current_user.set_password(new)
        audit("auth.password_change", f"user={current_user.id}", current_user)
        db.session.commit()
        flash("Password updated.", "success")
        return redirect(url_for("auth.account"))
    return render_template("auth/account.html")
