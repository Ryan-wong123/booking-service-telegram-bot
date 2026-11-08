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
- **Email** (Amazon SES SMTP or any SMTP server): booking confirmations to customer and host, cancellation and
  reschedule notices to the other party (with the reason), and a reminder `REMINDER_HOURS` (default 24) before the
  appointment. Reminders run from a CronJob / compose service and are sent exactly once (retried if delivery fails).
- **Password reset** by emailed single-use link (expires after `RESET_TOKEN_MINUTES`, throttled, no account
  enumeration), plus change-password on the Account page.
- **Database migrations** with Flask-Migrate/Alembic (`migrations/`); a test fails if the models and migrations drift.
- **Backups** of PostgreSQL to S3 (verified before upload) with a restore script.
- **CI** (GitHub Actions): lint, tests on SQLite and PostgreSQL, migration check, image build + smoke test, optional ECR publish.
- `/healthz` (liveness) and `/readyz` (database) endpoints; structured logs to stdout.

## Configuration (environment variables)
See `.env.example`. Key ones: `SECRET_KEY` (**required** when `APP_ENV=production`), `DATABASE_URL`
(PostgreSQL only; defaults to `postgresql://booking:booking@localhost:5432/booking`), `SUPERADMIN_EMAIL`/`SUPERADMIN_PASSWORD` (first-run bootstrap),
`APP_TIMEZONE`, `MAX_ACTIVE_BOOKINGS`, `ALLOW_REGISTRATION`, `MIN_PASSWORD_LENGTH`, `SMTP_*`/`MAIL_FROM`/`APP_BASE_URL`
(email), `REMINDER_HOURS`, `ZOOM_*` (optional).

## Run locally
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
# Start only the database (data persists in the Docker volume `booking_pgdata`):
export POSTGRES_PASSWORD=booking
docker compose up -d db
export DATABASE_URL=postgresql://booking:booking@localhost:5432/booking
export SUPERADMIN_EMAIL=admin@example.com SUPERADMIN_PASSWORD='a-long-password-here'
flask --app wsgi init-db          # applies migrations + seeds the first super admin
flask --app wsgi run --debug
flask --app wsgi send-reminders   # what the reminder job runs
```
Create more users from the admin UI, or `flask --app wsgi create-user EMAIL "Name" staff`.

## Database changes (migrations)
```bash
# after editing app/models.py:
flask --app wsgi db migrate -m "describe the change"   # review the generated file in migrations/versions/
flask --app wsgi db upgrade                            # apply it (init-db also does this)
```
Commit the new migration file with the model change.

## Local email testing
`docker compose --profile dev up` also starts Mailpit, a fake inbox at http://localhost:8025. Set `SMTP_HOST=mailpit`,
`SMTP_PORT=1025`, `SMTP_STARTTLS=false` in `.env` to see every email the portal sends.

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
- Email is plain text and in-app only for status; there is no SMS/push channel.
- Amazon SES starts in *sandbox* mode (can only email verified addresses): request production access before launch.
- A reminder goes out once per booking, `REMINDER_HOURS` before the start (the CronJob runs every 10 minutes).
- Single-region, single-node by default (k3s on one EC2 instance). See the deploy guide for what that implies.
