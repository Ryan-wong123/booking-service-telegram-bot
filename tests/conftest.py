from datetime import timedelta

import os

import pytest

from app import create_app
from app.extensions import db
from app.models import CUSTOMER, STAFF, SUPERADMIN, Service, Slot, User
from app.timeutils import utcnow

PASSWORD = "correct-horse-battery"


@pytest.fixture()
def app(tmp_path):
    app = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "test",
            "WTF_CSRF_ENABLED": False,
            # Set TEST_DATABASE_URL to run the suite against PostgreSQL; default is a temp SQLite file.
            "SQLALCHEMY_DATABASE_URI": os.environ.get("TEST_DATABASE_URL") or f"sqlite:///{tmp_path / 'test.db'}",
            "MAX_ACTIVE_BOOKINGS": 2,
            "LOCKOUT_ATTEMPTS": 3,
        }
    )
    with app.app_context():
        db.create_all()
        db.session.add(Service(name="General", duration_minutes=30))
        db.session.commit()
        yield app
        db.session.remove()
        db.drop_all()


def make_user(email, role, name=None, active=True):
    user = User(email=email, name=name or email.split("@")[0], role=role, active=active)
    user.set_password(PASSWORD)
    db.session.add(user)
    db.session.commit()
    return user


@pytest.fixture()
def superadmin(app):
    return make_user("root@example.com", SUPERADMIN)


@pytest.fixture()
def staff(app):
    return make_user("staff@example.com", STAFF)


@pytest.fixture()
def customer(app):
    return make_user("cust@example.com", CUSTOMER)


@pytest.fixture()
def customer2(app):
    return make_user("cust2@example.com", CUSTOMER)


@pytest.fixture()
def make_slot(app, staff):
    counter = {"n": 0}

    def _make(hours_ahead=48, minutes=30, staff_user=None):
        counter["n"] += 1
        start = utcnow().replace(second=0, microsecond=0) + timedelta(hours=hours_ahead + counter["n"] * 2)
        slot = Slot(
            staff_id=(staff_user or staff).id,
            service_id=Service.query.first().id,
            start_at=start,
            end_at=start + timedelta(minutes=minutes),
        )
        db.session.add(slot)
        db.session.commit()
        return slot

    return _make


def login(client, email, password=PASSWORD):
    return client.post("/login", data={"email": email, "password": password}, follow_redirects=False)


@pytest.fixture()
def client(app):
    return app.test_client()
