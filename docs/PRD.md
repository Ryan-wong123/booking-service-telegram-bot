# Product Requirements Document (PRD) — Booking Portal

> **Keep this file current.** Any change to behaviour, roles, rules, configuration or scope must update this PRD in the
> same commit (see [Agents.md](Agents.md)). Describes the code as of the commit that last touched this file.

## 1. Overview

Booking Portal is a web application where **customers** book appointments with **staff**, and a **super admin**
manages people, services and oversight. It replaces an earlier Telegram bot; there is no Telegram integration any more.

**Goals**
- Let customers self-serve: find a free slot, book, reschedule and cancel without contacting anyone.
- Let staff publish their availability and manage who has booked them.
- Give a super admin control over users, services and an audit trail.
- Never double-book a slot; never lose a booking to a third-party outage (Zoom, email).
- Run cheaply (~$20-30/month) on a single AWS EC2 instance with Docker Compose and PostgreSQL, with **no downtime for deployments** and a **99% availability** target (about 7 hours of downtime per month) for unplanned failures.

**Non-goals (current scope)**
- Payments, invoices or deposits.
- SMS / push notifications (email only).
- Recurring/series appointments; waiting lists; group bookings.
- Multi-tenant / multi-organisation support; multi-language UI.
- Surviving an instance or Availability-Zone failure without interruption (multi-AZ, load balancer, Kubernetes); see limitations for the upgrade path.
- Calendar sync (Google/Outlook/ICS).

## 2. Users and roles

| Role | Who | Can do | Cannot do |
|---|---|---|---|
| **Customer** | Public, self-registers | Browse free slots by calendar and service; book; reschedule (same service); cancel (with confirmation); see upcoming/past bookings and staff cancellation reasons; reset/change own password | See other customers' data; manage slots |
| **Staff** | Created by a super admin | Publish availability (single or back-to-back slots); see who booked and their notes; cancel a booking (reason required, shown to the customer); mark a started appointment completed; remove free slots; own schedule only | See other staff's schedules; manage users/services |
| **Super admin** | Bootstrapped by `init-db`, or created by another super admin | Everything staff can do for their own schedule, plus: create/edit/deactivate users and change roles; unlock locked accounts; create/edit services; view and cancel any booking; read the audit log | Demote/deactivate themselves; remove the last active super admin |

## 3. Functional requirements

### 3.1 Accounts and authentication
- FR-A1 Customers can self-register with name, email and password (can be disabled with `ALLOW_REGISTRATION=false`). Self-registration only ever creates customers.
- FR-A2 Login by email + password. Failure message is identical for unknown email, wrong password and inactive account.
- FR-A3 After `LOCKOUT_ATTEMPTS` (5) consecutive failures an account is locked for `LOCKOUT_MINUTES` (15); a super admin can unlock it.
- FR-A4 Password minimum length `MIN_PASSWORD_LENGTH` (10). Passwords are stored hashed.
- FR-A5 Forgot password: an emailed link, single use, valid `RESET_TOKEN_MINUTES` (60); requests are throttled (one per 2 minutes per account); the response never reveals whether an email has an account. Completing a reset also unlocks the account.
- FR-A6 Logged-in users can change their password (requires the current password).
- FR-A7 After login, users land on their role's home: customer → `/slots`, staff → `/staff/`, super admin → `/admin/users`.
- FR-A8 Deactivated users cannot log in.

### 3.2 Services
- FR-S1 A **service** (appointment type) has a name (unique), description, duration in minutes (5–480), a "Zoom meeting" flag and an active flag. A default service "General" (30 min) is created on first run.
- FR-S2 Only a super admin manages services. Inactive services disappear from customer browsing and cannot be booked.

### 3.3 Availability (staff)
- FR-V1 Staff create slots by choosing service, date, first start time and a count (1–20); slots are created back-to-back, each as long as the service duration.
- FR-V2 Slots must start in the future and must not overlap another of the same staff member's active slots.
- FR-V3 A free slot can be removed. A booked slot cannot be removed until its booking is cancelled. Slots that have booking history are soft-deleted (kept for records, hidden and unbookable).
- FR-V4 The staff calendar shows each day as all-free / partly-booked / fully-booked.

### 3.4 Booking (customer)
- FR-B1 Customers see only future, free slots whose service and host are active. Browse by month calendar (Sunday-first), filter by service, click a day to see times; with no day selected, all days of the month are listed.
- FR-B2 Booking shows a confirmation page (service, time, host, optional note up to 500 chars) before it is made.
- FR-B3 **No double booking:** a slot can be claimed by exactly one customer even under concurrent requests.
- FR-B4 A customer may hold at most `MAX_ACTIVE_BOOKINGS` (3) upcoming confirmed bookings and may not hold two overlapping ones.
- FR-B5 Customers can reschedule an upcoming booking to a free slot **of the same service** (the old slot is freed; the new slot is claimed atomically; a failure leaves the original booking untouched).
- FR-B6 Customers can cancel their **own** upcoming booking after a confirmation page; the slot becomes bookable again. Other customers' booking IDs behave as "not found".
- FR-B7 Past bookings cannot be cancelled or rescheduled.
- FR-B8 "My bookings" lists upcoming bookings (with Zoom link, note, reschedule/cancel) and history (completed, past, cancelled — including who cancelled and why when it was not the customer).

### 3.5 Booking management (staff / super admin)
- FR-M1 Staff cancel a booking on their own slots with a **required** reason; the customer sees the reason.
- FR-M2 After an appointment has started, staff can mark it **completed** (not before).
- FR-M3 A super admin can list all bookings (filter by status, paginated) and cancel any upcoming one with a reason.
- FR-M4 Deactivating or demoting a staff member cancels their upcoming bookings (reason "Your host is no longer available."), retires their future slots, and flags how many customers were affected. Their slots can no longer be booked.

### 3.6 User administration (super admin)
- FR-U1 Create users of any role with a temporary password; edit name, role, active flag, and optionally set a new password; unlock accounts.
- FR-U2 Guardrails: a super admin cannot change their own role or deactivate themselves, and the last active super admin cannot be demoted or deactivated.
- FR-U3 Every consequential action is written to an **audit log** (login, registration, booking create/cancel/reschedule/complete, slot create/delete, user and service changes, password reset events), viewable by super admins.

### 3.7 Notifications (email)
- FR-N1 Booking confirmed → email to the customer and to the host (host also sees the customer's note).
- FR-N2 Booking cancelled → email to the other party/parties (everyone involved except the person who cancelled), including the reason.
- FR-N3 Booking rescheduled → email to the customer and the affected host(s).
- FR-N4 Reminder `REMINDER_HOURS` (24) before the start, sent **once** per booking; a booking made inside the window gets no separate reminder; a failed send is retried on the next run; rescheduling re-arms the reminder.
- FR-N5 Password reset link by email.
- FR-N6 A failure to send email must never fail or roll back a booking action.
- FR-N7 If `SMTP_HOST` is unset, email is disabled (logged, not sent).

### 3.8 Optional Zoom integration
- FR-Z1 For services flagged "Zoom", a **scheduled** Zoom meeting is created per booking (when Zoom credentials are configured) and its link shown to the customer and host.
- FR-Z2 Cancel/reschedule deletes the old meeting. If Zoom is down, the booking still succeeds and the user is told the host will share a link.

### 3.9 Time
- FR-T1 Times are stored in UTC and shown/entered in `APP_TIMEZONE` (default `Asia/Singapore`).

## 4. Non-functional requirements

| Area | Requirement |
|---|---|
| **Security** | CSRF token on every form; all state changes are POST; hashed passwords; login lockout; same-site relative redirects only (`next`); security headers incl. CSP, frame denial; secure, HttpOnly, SameSite cookies (Secure in production); `SECRET_KEY` mandatory in production; no secrets in the repository; ownership checks on all customer/staff resources; role checks on every protected route. |
| **Data integrity** | Atomic slot claim; foreign keys; history preserved via soft-delete; migrations are the only way to change the schema. |
| **Availability** | Target **99%** (≈7 h/month). Single EC2 instance with: CloudWatch auto-recovery, `restart: unless-stopped` containers with Docker enabled at boot, daily EBS snapshots, nightly verified S3 backup, an external uptime monitor on `/readyz`, log rotation and swap to avoid disk/memory exhaustion. Stateless web tier (sessions in signed cookies). `/healthz` (liveness) and `/readyz` (checks the database). **Deploys cause no downtime**: two app replicas behind the proxy are drained and replaced one at a time, and migrations must be backward compatible with the previous release (expand, then contract). An instance failure or OS reboot still causes a short outage (a few minutes): it is recovered, not failed over. |
| **Recoverability** | Nightly verified PostgreSQL dump to S3 (30-day retention) plus daily EBS snapshots (7 kept); documented restore. |
| **Observability** | Structured logs to stdout; audit log in the database. |
| **Performance** | Month-scoped slot queries, indexes on slot start/staff and booking foreign keys, paginated admin lists. Target scale: hundreds of users, thousands of slots. |
| **Privacy** | Stores name, email, password hash and booking notes only. Email addresses are shown to staff for their own bookings and to super admins. |
| **Portability** | PostgreSQL only in production (SQLite used by the default test run). |
| **Accessibility / UX** | Responsive Bootstrap UI; works without custom JavaScript (confirmation pages instead of JS dialogs). |

## 5. Configuration (environment variables)

| Variable | Default | Purpose |
|---|---|---|
| `APP_ENV` | `development` | `production` enforces `SECRET_KEY`, secure cookies, proxy trust |
| `SECRET_KEY` | — | Signs sessions and reset tokens (**required** in production) |
| `DATABASE_URL` | `postgresql://booking:booking@localhost:5432/booking` | Database |
| `APP_TIMEZONE` | `Asia/Singapore` | Display/entry timezone |
| `MAX_ACTIVE_BOOKINGS` | `3` | Upcoming bookings per customer |
| `ALLOW_REGISTRATION` | `true` | Open customer sign-up |
| `LOCKOUT_ATTEMPTS` / `LOCKOUT_MINUTES` | `5` / `15` | Login lockout |
| `MIN_PASSWORD_LENGTH` | `10` | Password policy |
| `SESSION_HOURS` / `SESSION_COOKIE_SECURE` / `TRUST_PROXY` | `8` / prod: true / prod: true | Session and proxy handling |
| `SMTP_HOST` `SMTP_PORT` `SMTP_USERNAME` `SMTP_PASSWORD` `SMTP_STARTTLS` `MAIL_FROM` | — / `587` / — / — / `true` / `no-reply@localhost` | Email (SES SMTP or any SMTP) |
| `APP_BASE_URL` | `http://localhost:8000` | Absolute links in emails |
| `REMINDER_HOURS` / `RESET_TOKEN_MINUTES` | `24` / `60` | Reminder window; reset-link lifetime |
| `ZOOM_ACCOUNT_ID` `ZOOM_CLIENT_ID` `ZOOM_CLIENT_SECRET` | — | Optional Zoom (Server-to-Server OAuth) |
| `SUPERADMIN_EMAIL` `SUPERADMIN_PASSWORD` `SUPERADMIN_NAME` | — | First-run super admin (`init-db`, only if none exists) |
| `LOG_LEVEL` | `INFO` | Logging |
| `DRAIN_FILE` | `/tmp/draining` | While this file exists `/healthz` returns 503 (used by `deploy/deploy.sh` to drain a replica) |
| Production Compose: `DOMAIN` `ACME_EMAIL` | — | Public hostname and Let's Encrypt contact for automatic HTTPS (Caddy) |
| Backup job: `S3_BUCKET` `S3_PREFIX` `AWS_DEFAULT_REGION` | — / `booking` / — | Nightly backup |

## 6. Success criteria
- A customer can register, book, reschedule and cancel without admin help.
- Concurrent attempts on the same slot produce exactly one booking.
- A Zoom or SMTP outage never prevents a booking.
- The test suite (see Architecture §9) passes on SQLite and PostgreSQL, and migrations match the models.
- A fresh EC2 instance can be brought to a working HTTPS deployment by following `docs/DEPLOY_AWS_EC2.md`.
- Measured availability stays at or above 99% per month as reported by the external uptime monitor.
- Deploying a new version produces zero failed requests (checked in CI by sending continuous traffic during `deploy/deploy.sh`).

## 7. Known limitations and future work
- Email only, plain text; Amazon SES starts in sandbox mode and needs production access.
- One reminder per booking; no per-user notification preferences.
- Single instance by design: deploys are zero-downtime, but an instance failure, an OS reboot (kernel updates) or a PostgreSQL restart/upgrade still causes a short outage. For surviving those the upgrade path is RDS Multi-AZ plus two app nodes behind a load balancer in two Availability Zones (roughly double the cost).
- Password reset needs working email; otherwise a super admin resets passwords.
- No rate limiting beyond account lockout and reset throttling (add an ingress/WAF limit for public exposure).
- Deployment is manual (`git pull` + `docker compose up -d --build` on the server); CI builds and tests but does not deploy.
- The Docker images are built and smoke-tested in CI, and the Compose files are validated with `docker compose config`, but the full production stack and the AWS steps (Caddy certificate issuance, SES, S3, CloudWatch, DLM) have not been run end to end. Treat the deploy guide as a starting point.
