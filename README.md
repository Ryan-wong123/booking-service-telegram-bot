# Booking Portal

A web portal for booking appointments, with three roles. (This project used to be a Telegram bot; all
Telegram features have been removed.)

| Role | Can do |
|---|---|
| **Customer** | Self-register, browse free slots (calendar, by service), book, reschedule, cancel (with confirmation), see history and any cancellation reason from staff |
| **Staff** | Publish availability (single or back-to-back slots), see who booked, cancel a booking with a reason, mark appointments completed, remove free slots |
| **Super admin** | Everything above for their own schedule, plus manage users and roles, manage services (name, duration, Zoom on/off), view/cancel all bookings, read the audit log, unlock accounts |

## Features and rules
- Atomic booking (a single conditional `UPDATE`), so two people can never take the same slot.
- Max active bookings per customer (`MAX_ACTIVE_BOOKINGS`, default 3) and no overlapping bookings.
- Slots must be in the future and cannot overlap a staff member's other slots.
- Services replace the old hardcoded "General" type; each has a duration and optional Zoom meeting.
- Optional Zoom (scheduled meetings, token cached, link deleted on cancel/reschedule). A Zoom outage never blocks a booking.
- Times are stored in UTC and displayed in `APP_TIMEZONE` (default `Asia/Singapore`).
- Security: hashed passwords, CSRF on every form, state changes only via POST, login lockout, open-redirect protection,
  security headers/CSP, ownership checks, no secrets in the repo, audit log.
- Deactivating or demoting a staff member cancels their upcoming bookings; customers see the reason in their account.
- `/healthz` (liveness) and `/readyz` (database) endpoints; structured logs to stdout.

## Configuration (environment variables)
See `.env.example`. Key ones: `SECRET_KEY` (**required** when `APP_ENV=production`), `DATABASE_URL`
(PostgreSQL only; defaults to `postgresql://booking:booking@localhost:5432/booking`), `SUPERADMIN_EMAIL`/`SUPERADMIN_PASSWORD` (first-run bootstrap),
`APP_TIMEZONE`, `MAX_ACTIVE_BOOKINGS`, `ALLOW_REGISTRATION`, `MIN_PASSWORD_LENGTH`, `ZOOM_*` (optional).

## Run locally
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
# Start only the database (data persists in the Docker volume `booking_pgdata`):
export POSTGRES_PASSWORD=booking
docker compose up -d db
export DATABASE_URL=postgresql://booking:booking@localhost:5432/booking
export SUPERADMIN_EMAIL=admin@example.com SUPERADMIN_PASSWORD='a-long-password-here'
flask --app wsgi init-db
flask --app wsgi run --debug
```
Create more users from the admin UI, or `flask --app wsgi create-user EMAIL "Name" staff`.

## Tests
```bash
pytest        # uses a throwaway SQLite file, no database server needed
```

## Docker
```bash
cp .env.example .env     # edit the secrets first
docker compose up --build
```
PostgreSQL runs in its own container with data on the named volume `booking_pgdata`, so it survives restarts and
rebuilds (`docker compose down -v` deletes it). The app is at http://localhost:8000 (`init` runs once to create tables and the super admin).
Over plain HTTP set `SESSION_COOKIE_SECURE=false`, otherwise browsers drop the login cookie.

## Deploy to AWS EC2 with Docker + Kubernetes
See **[docs/DEPLOY_AWS_EC2.md](docs/DEPLOY_AWS_EC2.md)** (single EC2 node running k3s; manifests in `k8s/`).

## Layout
```
app/                Flask application (blueprints: auth, customer, staff, admin, health)
app/services/       booking rules (booking.py) and optional Zoom client (zoom.py)
app/templates/      Jinja templates (Bootstrap via CDN)
k8s/                Kubernetes manifests (kustomize)
tests/              pytest suite
Dockerfile, docker-compose.yml, wsgi.py
```

## Known limitations
- **No reminders or notifications.** Telegram was the only channel; users now see status and cancellation reasons in
  the portal only. Adding email (SMTP/Amazon SES) is the natural next step.
- **No schema migrations yet.** `flask init-db` uses `create_all`, which creates missing tables but does not alter existing
  ones. Add Flask-Migrate/Alembic before changing the schema of a live database.
- No self-service password reset (a super admin resets passwords).
