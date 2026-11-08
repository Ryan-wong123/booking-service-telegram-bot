import logging
import os
import secrets
import time

import click
from flask import Flask, flash, redirect, render_template, request, url_for
from flask_login import current_user
from flask_wtf.csrf import CSRFError
from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from werkzeug.middleware.proxy_fix import ProxyFix

from .config import load_config
from .extensions import csrf, db, login_manager
from .models import CUSTOMER, STAFF, SUPERADMIN, Service, User
from .timeutils import to_local


def create_app(test_config: dict | None = None) -> Flask:
    app = Flask(__name__)
    app.config.update(load_config())
    if test_config:
        app.config.update(test_config)

    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    if not app.config["SECRET_KEY"]:
        if app.config["APP_ENV"] == "production":
            raise RuntimeError("SECRET_KEY must be set when APP_ENV=production")
        app.config["SECRET_KEY"] = secrets.token_hex(32)
        app.logger.warning("SECRET_KEY not set: using a random key (sessions reset on restart)")

    if app.config["TRUST_PROXY"]:
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    db.init_app(app)
    csrf.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = "auth.login"
    login_manager.login_message_category = "warning"

    from .blueprints import admin, auth, customer, health, staff

    for module in (health, auth, customer, staff, admin):
        app.register_blueprint(module.bp)

    _register_filters(app)
    _register_hooks(app)
    _register_errors(app)
    _register_cli(app)
    return app


def role_home(user) -> str:
    return {
        SUPERADMIN: url_for("admin.users"),
        STAFF: url_for("staff.dashboard"),
        CUSTOMER: url_for("customer.slots"),
    }[user.role]


def _register_filters(app: Flask) -> None:
    @app.template_filter("dt")
    def fmt_dt(value):
        return to_local(value).strftime("%a %d %b %Y, %H:%M") if value else ""

    @app.template_filter("tm")
    def fmt_time(value):
        return to_local(value).strftime("%H:%M") if value else ""

    @app.template_filter("dkey")
    def fmt_date_key(value):
        return to_local(value).strftime("%Y-%m-%d")

    @app.template_filter("dlong")
    def fmt_date_long(value):
        return to_local(value).strftime("%A, %d %B %Y")

    @app.context_processor
    def inject_globals():
        return {"tz_name": app.config["APP_TIMEZONE"], "role_home": role_home}


def _register_hooks(app: Flask) -> None:
    @app.after_request
    def security_headers(response):
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; style-src 'self' https://cdn.jsdelivr.net; "
            "script-src 'self' https://cdn.jsdelivr.net; img-src 'self' data:; "
            "frame-ancestors 'none'; form-action 'self'",
        )
        if request.is_secure:
            response.headers.setdefault("Strict-Transport-Security", "max-age=31536000")
        if current_user.is_authenticated:
            response.headers["Cache-Control"] = "no-store"
        return response


def _register_errors(app: Flask) -> None:
    def render_error(code, title, message):
        return render_template("error.html", code=code, title=title, message=message), code

    @app.errorhandler(403)
    def forbidden(_):
        return render_error(403, "Forbidden", "You don't have permission to view this page.")

    @app.errorhandler(404)
    def not_found(_):
        return render_error(404, "Not found", "We couldn't find that page.")

    @app.errorhandler(500)
    def server_error(_):
        db.session.rollback()
        return render_error(500, "Something went wrong", "Please try again in a moment.")

    @app.errorhandler(CSRFError)
    def csrf_failed(_):
        flash("Your session expired or the form was invalid. Please try again.", "warning")
        return redirect(request.referrer or url_for("auth.login"))


def _register_cli(app: Flask) -> None:
    @app.cli.command("init-db")
    def init_db():
        """Create tables, a default service and (if configured) the first super admin. Idempotent."""
        for attempt in range(30):  # wait for the database (e.g. Postgres still starting)
            try:
                db.session.execute(text("SELECT 1"))
                break
            except OperationalError:
                click.echo(f"Waiting for database ({attempt + 1}/30)...")
                time.sleep(2)
        else:
            raise click.ClickException("Database is not reachable")

        db.create_all()
        if not Service.query.first():
            db.session.add(Service(name="General", description="General appointment", duration_minutes=30))
        email, password = app.config["SUPERADMIN_EMAIL"], app.config["SUPERADMIN_PASSWORD"]
        if email and password and not User.query.filter_by(role=SUPERADMIN).first():
            _make_user(app, email, app.config["SUPERADMIN_NAME"], password, SUPERADMIN)
            click.echo(f"Created super admin {email}")
        db.session.commit()
        click.echo("Database ready.")

    @app.cli.command("create-user")
    @click.argument("email")
    @click.argument("name")
    @click.argument("role", type=click.Choice([SUPERADMIN, STAFF, CUSTOMER]))
    @click.password_option()
    def create_user(email, name, role, password):
        """Create a user from the command line."""
        _make_user(app, email, name, password, role)
        db.session.commit()
        click.echo(f"Created {role} {email}")


def _make_user(app, email, name, password, role):
    if len(password) < app.config["MIN_PASSWORD_LENGTH"]:
        raise click.ClickException(f"Password must be at least {app.config['MIN_PASSWORD_LENGTH']} characters")
    user = User(email=email.strip().lower(), name=name.strip(), role=role)
    user.set_password(password)
    db.session.add(user)
    return user
