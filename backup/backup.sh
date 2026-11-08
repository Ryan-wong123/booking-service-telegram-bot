#!/bin/bash
# Dump the booking database and upload it to S3. Credentials come from the EC2 instance role
# (no keys in the cluster). A dump is only uploaded after pg_restore proves it is readable.
set -euo pipefail

: "${S3_BUCKET:?S3_BUCKET is required}"
: "${PGPASSWORD:?PGPASSWORD is required}"
PREFIX="${S3_PREFIX:-booking}"
WORKDIR="${BACKUP_TMP:-/tmp}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
FILE="$WORKDIR/booking-$STAMP.dump"
trap 'rm -f "$FILE"' EXIT

echo "Dumping ${PGDATABASE:-booking} from ${PGHOST:-postgres}..."
pg_dump -h "${PGHOST:-postgres}" -p "${PGPORT:-5432}" -U "${PGUSER:-booking}" -d "${PGDATABASE:-booking}" -Fc -f "$FILE"

echo "Verifying dump..."
pg_restore -l "$FILE" >/dev/null

echo "Uploading to s3://$S3_BUCKET/$PREFIX/ ($(du -h "$FILE" | cut -f1))..."
aws s3 cp "$FILE" "s3://$S3_BUCKET/$PREFIX/booking-$STAMP.dump" --only-show-errors \
  --sse AES256
echo "Backup complete: booking-$STAMP.dump"
