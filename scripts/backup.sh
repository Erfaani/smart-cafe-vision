#!/usr/bin/env bash
# Smart Café Vision — database backup.
#
# Works two ways, auto-detected:
#   - Docker install: dumps through `docker compose exec` (default)
#   - Non-Docker (systemd) install: dumps with a local `pg_dump` when
#     SMARTCAFE_NO_DOCKER=1 is set -- see deployment/systemd/.
#
# Usage:
#   scripts/backup.sh                    # backup now
#   BACKUP_DIR=/mnt/nas/backups scripts/backup.sh
#   BACKUP_RETENTION_DAYS=30 scripts/backup.sh
#
# Safe to run from a cron job or a systemd timer (deployment/systemd/
# smartcafe-backup.timer) with no terminal attached: it never prompts.
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

if [ -f .env ]; then
  # Only the POSTGRES_* names, not the whole file -- a backup script has no
  # business exporting every secret in .env into its own process environment.
  # shellcheck disable=SC1090
  set -a
  POSTGRES_DB=$(grep -E '^POSTGRES_DB=' .env | tail -1 | cut -d= -f2-)
  POSTGRES_USER=$(grep -E '^POSTGRES_USER=' .env | tail -1 | cut -d= -f2-)
  set +a
fi

POSTGRES_DB="${POSTGRES_DB:-smartcafe}"
POSTGRES_USER="${POSTGRES_USER:-smartcafe}"
BACKUP_DIR="${BACKUP_DIR:-$(pwd)/backups}"
BACKUP_RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-14}"

mkdir -p "$BACKUP_DIR"

timestamp="$(date +%Y%m%d-%H%M%S)"
outfile="$BACKUP_DIR/smartcafe-${timestamp}.sql.gz"
tmpfile="${outfile}.partial"

# --clean --if-exists: the dump includes DROP statements ahead of each CREATE,
# so scripts/restore.sh can load it into a database that already has data
# (the normal case -- restoring is disaster recovery, not first-time setup)
# without a "relation already exists" error stopping it halfway through.
dump_cmd=(pg_dump --clean --if-exists -U "$POSTGRES_USER" "$POSTGRES_DB")

echo "Backing up '$POSTGRES_DB' to $outfile ..."

if [ "${SMARTCAFE_NO_DOCKER:-0}" = "1" ]; then
  "${dump_cmd[@]}" | gzip > "$tmpfile"
else
  docker compose exec -T postgres "${dump_cmd[@]}" | gzip > "$tmpfile"
fi

# Only replace the real filename once the dump has actually finished --
# a backup script killed mid-write must never leave a truncated file behind
# with a name that looks like a complete, restorable backup.
mv "$tmpfile" "$outfile"

size="$(du -h "$outfile" | cut -f1)"
echo "Backup complete: $outfile ($size)"

if [ "$BACKUP_RETENTION_DAYS" -gt 0 ]; then
  deleted=$(find "$BACKUP_DIR" -maxdepth 1 -name 'smartcafe-*.sql.gz' -mtime "+${BACKUP_RETENTION_DAYS}" -print -delete | wc -l)
  if [ "$deleted" -gt 0 ]; then
    echo "Pruned $deleted backup(s) older than ${BACKUP_RETENTION_DAYS} days."
  fi
fi
