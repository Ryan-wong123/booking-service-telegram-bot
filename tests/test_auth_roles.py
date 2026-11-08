from app.extensions import db
from app.models import CUSTOMER, User

from .conftest import PASSWORD, login


def test_healthz_and_readyz(client):
    assert client.get("/healthz").status_code == 200
    assert client.get("/readyz").status_code == 200


def test_login_redirects_by_role(client, superadmin, staff, customer):
    assert login(client, "root@example.com").headers["Location"].endswith("/admin/users")
    client.post("/logout")
    assert login(client, "staff@example.com").headers["Location"].endswith("/staff/")
    client.post("/logout")
    assert login(client, "cust@example.com").headers["Location"].endswith("/slots")


def test_role_separation(client, staff, customer):
    login(client, "cust@example.com")
    assert client.get("/staff/").status_code == 403
    assert client.get("/admin/users").status_code == 403
    client.post("/logout")
    login(client, "staff@example.com")
    assert client.get("/slots").status_code == 403
    assert client.get("/admin/users").status_code == 403


def test_anonymous_redirected_to_login(client):
    assert client.get("/slots").status_code == 302
    assert "/login" in client.get("/admin/users").headers["Location"]


def test_open_redirect_blocked(client, customer):
    resp = client.post("/login?next=https://evil.example", data={"email": "cust@example.com", "password": PASSWORD})
    assert "evil.example" not in resp.headers["Location"]
    client.post("/logout")
    resp = client.post("/login?next=//evil.example", data={"email": "cust@example.com", "password": PASSWORD})
    assert "evil.example" not in resp.headers["Location"]


def test_lockout_after_failed_attempts(client, customer):
    for _ in range(3):
        assert login(client, "cust@example.com", "wrong-password").status_code == 401
    # Even the right password is refused while locked.
    assert login(client, "cust@example.com").status_code == 429


def test_inactive_user_cannot_login(client, app):
    from .conftest import make_user

    make_user("gone@example.com", CUSTOMER, active=False)
    assert login(client, "gone@example.com").status_code == 401


def test_register_creates_customer_only(client):
    resp = client.post(
        "/register",
        data={"name": "New", "email": "New@Example.com", "password": PASSWORD, "confirm": PASSWORD, "role": "superadmin"},
    )
    assert resp.status_code == 302
    user = User.query.filter_by(email="new@example.com").one()
    assert user.role == CUSTOMER


def test_register_rejects_short_password(client):
    resp = client.post("/register", data={"name": "A", "email": "a@b.co", "password": "short", "confirm": "short"})
    assert resp.status_code == 400


def test_register_closed(app, client):
    app.config["ALLOW_REGISTRATION"] = False
    assert client.get("/register").status_code == 302


def test_csrf_enforced_when_enabled(tmp_path):
    from app import create_app

    app = create_app({"SECRET_KEY": "x", "SQLALCHEMY_DATABASE_URI": f"sqlite:///{tmp_path/'c.db'}"})
    with app.app_context():
        db.create_all()
    resp = app.test_client().post("/login", data={"email": "a@b.co", "password": "x"})
    assert resp.status_code == 302  # CSRF failure redirects back with a flash, no login


def test_security_headers(client):
    resp = client.get("/login")
    assert resp.headers["X-Frame-Options"] == "DENY"
    assert "Content-Security-Policy" in resp.headers


def test_production_requires_secret_key(monkeypatch):
    import pytest

    from app import create_app

    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.delenv("SECRET_KEY", raising=False)
    with pytest.raises(RuntimeError):
        create_app()
