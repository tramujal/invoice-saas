#!/usr/bin/env bash
# Backup strategy for the self-hosted Postgres in docker-compose.prod.yml.
#
# ONLY relevant to that self-hosted path -- if you're using Neon (the
# managed path in README.md's own Deployment section), Neon already
# takes continuous, automatic backups with point-in-time restore built
# in; this script has nothing to do and shouldn't be run there.
#
# Usage:
#   ./scripts/backup_postgres.sh [output-directory]
#
# Produces one gzip-compressed pg_dump per run, named with a UTC
# timestamp, so repeated runs never overwrite each other. Runs the dump
# INSIDE the `db` container via `docker compose exec` -- never needs
# Postgres exposed to the host (docker-compose.prod.yml deliberately
# doesn't publish its port, see that file's own comment).
#
# Recommended: a daily cron entry (or systemd timer) on the host running
# this stack, e.g.:
#   0 3 * * * cd /path/to/this/repo && ./scripts/backup_postgres.sh /var/backups/invoicing >> /var/log/invoicing-backup.log 2>&1
#
# Restore (destructive -- drops and recreates the target database first):
#   gunzip -c /var/backups/invoicing/invoicing_20260731T030000Z.sql.gz | \
#     docker compose -f docker-compose.prod.yml exec -T db psql -U invoicing -d invoicing

set -euo pipefail

COMPOSE_FILE="$(dirname "$0")/../docker-compose.prod.yml"
OUTPUT_DIR="${1:-./backups}"
POSTGRES_USER="${POSTGRES_USER:-invoicing}"
POSTGRES_DB="${POSTGRES_DB:-invoicing}"
TIMESTAMP="$(date -u +%Y%m%dT%H%M%SZ)"
OUTPUT_FILE="${OUTPUT_DIR}/${POSTGRES_DB}_${TIMESTAMP}.sql.gz"

mkdir -p "$OUTPUT_DIR"

echo "Backing up ${POSTGRES_DB} to ${OUTPUT_FILE} ..."
docker compose -f "$COMPOSE_FILE" exec -T db \
  pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --no-owner --no-acl \
  | gzip > "$OUTPUT_FILE"

echo "Done: $(du -h "$OUTPUT_FILE" | cut -f1) written."

# Retention: delete backups older than 14 days. Adjust to your own
# requirements -- this is a starting point, not a policy recommendation.
find "$OUTPUT_DIR" -name "${POSTGRES_DB}_*.sql.gz" -mtime +14 -delete
