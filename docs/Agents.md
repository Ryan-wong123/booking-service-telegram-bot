# Agents.md — Instructions for AI coding agents (and humans)

This file tells any AI agent working in this repository how to behave. Read it before changing anything.

## 1. Golden rule: keep the docs in sync

**Whenever you change anything, you MUST update [PRD.md](PRD.md) and [Architecture.md](Architecture.md) in the same
change/commit.** A change is not finished until the docs match the code.

| If you change… | Update… |
|---|---|
| Behaviour, rules, roles, permissions, limits, emails, user-visible flows, scope | **PRD.md** (functional requirements, non-goals, limitations) |
| Environment variables / defaults | **PRD.md** §5 *and* `.env.example`, `docker-compose*.yml`, README |
| Models, columns, indexes, constants | **Architecture.md** §4 *and* add an Alembic migration |
| Routes, blueprints, CLI commands | **Architecture.md** §6–§7 (and PRD.md if user-visible) |
| Files/folders, layering, dependencies, design decisions | **Architecture.md** §2, §3, §5 |
| Docker, compose (local and prod), Caddy, CI, backups, deployment steps | **Architecture.md** §8–§9 *and* `docs/DEPLOY_AWS_EC2.md` |
| Tests added/removed in a way that changes coverage | **Architecture.md** §9 |

If nothing in the table applies, say so in your summary ("docs: no update needed, because …"). Never leave the docs
describing behaviour that no longer exists. If you find the docs already wrong, fix them.

## 2. Project in one paragraph

Flask web portal for appointment booking with three roles (customer, staff, super admin), PostgreSQL, email
notifications/reminders, optional Zoom, deployed with Docker Compose (Caddy + app + PostgreSQL) on a single AWS EC2 instance. All product behaviour is in
[PRD.md](PRD.md); structure and design decisions are in [Architecture.md](Architecture.md). The old Telegram bot no
longer exists — do not reintroduce Telegram code.

## 3. Working agreements

1. **Business rules live in `app/services/booking.py`.** Blueprints stay thin (parse → authorise → call service → render).
2. **Schema changes need a migration.** Edit `app/models.py`, run `flask db migrate -m "..."`, review the generated file, commit
   it. `tests/test_migrations.py` fails if models and migrations drift. Keep migrations backward compatible with the previous release.
3. **Preserve the invariants** (each has tests — keep them passing and add tests for new behaviour):
   - A slot can be claimed by only one customer (atomic conditional `UPDATE`; never "check then insert").
   - Cancel/reschedule/complete are scoped to the owner or the owning staff member; non-owners get 404.
   - Side effects (Zoom, email) happen after the DB commit and must never fail a booking.
   - Datetimes are naive UTC in the database; convert only at the edges.
   - Every state-changing route is POST with CSRF; every protected route uses `roles_required`.
4. **Security:** never commit secrets, tokens, passwords or real credentials (code, tests, docs, manifests, history).
   Configuration comes from environment variables. `.env.example` holds placeholders only; the real `.env` exists only on the server.
   Keep user-facing messages free of account enumeration (login, forgot password).
5. **Dependencies:** pin exact versions in `requirements.txt` (runtime) / `requirements-dev.txt` (tests). Add only what is needed.
6. **Style:** follow the existing code; keep `pyflakes` clean; no dead code, no commented-out blocks.
7. **Templates:** no business logic; escape by default (never `|safe` user input); no inline `<script>`/`style=` (CSP).

## 4. Before you finish a change

Run, and report the real results (do not claim success you did not observe):

```bash
pyflakes app tests wsgi.py
pytest -q                                              # SQLite
TEST_DATABASE_URL=postgresql://booking:booking@localhost:5432/booking_test pytest -q   # PostgreSQL, if available
```

If you changed deployment files you could not execute (Docker, Compose, AWS), say clearly that they were validated only
statically (e.g. YAML parse) and not run.

## 5. Git conventions

- **Author and committer must be the human owner of the repository** (use the identity already configured in
  `git config user.name` / `user.email`, or ask). **Never** set an AI/bot as author or committer, and **never** add
  `Co-Authored-By:` or other AI attribution trailers or session links to commit messages or pull requests.
- Small, focused commits with imperative subject lines (e.g. "Add reminder retry on SMTP failure"); explain *why* in the body.
- Do not push to or rewrite `main`. Work on a feature branch; open a pull request only when asked.
- Do not rewrite or force-push shared history unless the owner explicitly asks.
- Never commit generated or local files: `.env`, `*.db`, `venv/`, `__pycache__/`, `instance/`, `caddy_data`/certificates.

## 6. Where things are

| Need | Look at |
|---|---|
| What the product must do | [PRD.md](PRD.md) |
| How it is built, data model, routes, deployment | [Architecture.md](Architecture.md) |
| How to deploy to AWS EC2 (Docker Compose) | [DEPLOY_AWS_EC2.md](DEPLOY_AWS_EC2.md) |
| How to run and test locally | `README.md` |
| Entry point Claude Code loads automatically | `CLAUDE.md` (points here) |
| Booking rules | `app/services/booking.py` |
| Emails and reminders | `app/services/notifications.py`, `app/services/email.py` |
| Schema | `app/models.py`, `migrations/versions/` |
