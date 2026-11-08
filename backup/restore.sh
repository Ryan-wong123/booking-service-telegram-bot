#!/bin/bash
# Restore a dump from S3 into the database. DESTRUCTIVE: replaces current data.
#   restore.sh                 -> lists the available backups
#   restore.sh booking-2026...dump
set -euo pipefail
: "${S3_BUCKET:?S3_BUCKET is required}"
PREFIX="${S3_PREFIX:-booking}"

if [ $# -eq 0 ]; then
  aws s3 ls "s3://$S3_BUCKET/$PREFIX/"
  exit 0
fi
: "${PGPASSWORD:?PGPASSWORD is required}"
FILE="${BACKUP_TMP:-/tmp}/restore.dump"
trap 'rm -f "$FILE"' EXIT
aws s3 cp "s3://$S3_BUCKET/$PREFIX/$1" "$FILE" --only-show-errors
pg_restore -h "${PGHOST:-postgres}" -p "${PGPORT:-5432}" -U "${PGUSER:-booking}" -d "${PGDATABASE:-booking}" \
  --clean --if-exists --no-owner "$FILE"
echo "Restored $1"
