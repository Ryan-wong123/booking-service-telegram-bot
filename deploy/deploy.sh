#!/usr/bin/env bash
# Zero-downtime deploy for the single-instance Compose stack.
#
# Two app replicas (web1, web2) run behind Caddy. For each replica in turn we:
#   1. DRAIN it  - /healthz starts returning 503, Caddy stops routing to it, in-flight requests finish
#   2. REPLACE it - new container from the freshly built image, wait until it is healthy
#   3. SETTLE    - give Caddy time to put it back in rotation before touching the other replica
# so at least one healthy replica is always serving. Database migrations run first and therefore must be
# backward compatible with the previous release (add before you use; remove a release later).
#
# Usage:  ./deploy/deploy.sh          (run from anywhere; needs .env next to docker-compose.prod.yml)
set -euo pipefail

cd "$(dirname "$0")/.."
COMPOSE="docker compose -f docker-compose.prod.yml"
DRAIN_WAIT="${DRAIN_WAIT:-6}"     # > Caddy health_interval (2s) so the replica is out of rotation
SETTLE_WAIT="${SETTLE_WAIT:-6}"

echo "==> Building the image (the running site is untouched)"
$COMPOSE build

echo "==> Database up, applying migrations"
$COMPOSE up -d --wait db
$COMPOSE run --rm --no-deps init

for svc in web1 web2; do
  if $COMPOSE ps --status running --services | grep -qx "$svc"; then
    echo "==> Draining $svc"
    $COMPOSE exec -T "$svc" touch /tmp/draining || true
    sleep "$DRAIN_WAIT"
  fi
  echo "==> Replacing $svc"
  $COMPOSE up -d --no-deps --force-recreate --wait "$svc"
  echo "==> Waiting for Caddy to put $svc back in rotation"
  sleep "$SETTLE_WAIT"
done

echo "==> Restarting the reminder loop on the new code"
$COMPOSE up -d --no-deps --force-recreate reminders

echo "==> Making sure Caddy is up and has the latest config (graceful reload, no dropped connections)"
$COMPOSE up -d --no-deps --wait caddy
$COMPOSE exec -T caddy caddy reload --config /etc/caddy/Caddyfile

echo "==> Deploy finished"
$COMPOSE ps
