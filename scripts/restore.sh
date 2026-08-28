#!/usr/bin/env bash
# Smart Café Vision — database restore.
#
# Destructive: replaces every table in the live database with the backup's
# contents (scripts/backup.sh dumps with --clean --if-exists). Requires
# typing the database name to confirm, same as scripts/backup.sh is auto,
# unattended, and never prompts -- restore is the opposite on purpose.
#
# Usage:
#   scripts/restore.sh backups/smartcafe-20260827-030000.sql.gz
#   scripts/restore.sh backups/smartcafe-20260827-030000.sql.gz --yes   # skip the prompt
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

backup_file="${1:-}"
confirm_flag="${2:-}"

if [ -z "$backup_file" ]; then
  echo "Usage: scripts/restore.sh <backup-file.sql.gz> [--yes]" >&2
  exit 1
fi

if [ ! -f "$backup_file" ]; then
  echo "No such file: $backup_file" >&2
  exit 1
fi

if [ -f .env ]; then
  # shellcheck disable=SC1090
  set -a
  POSTGRES_DB=$(grep -E '^POSTGRES_DB=' .env | tail -1 | cut -d= -f2-)
  POSTGRES_USER=$(grep -E '^POSTGRES_USER=' .env | tail -1 | cut -d= -f2-)
  set +a
fi

POSTGRES_DB="${POSTGRES_DB:-smartcafe}"
POSTGRES_USER="${POSTGRES_USER:-smartcafe}"

if [ "$confirm_flag" != "--yes" ] && [ "$confirm_flag" != "-y" ]; then
  echo "This REPLACES every table in the '${POSTGRES_DB}' database with the"
  echo "contents of: $backup_file"
  echo "Everything written since that backup was taken is lost."
  echo
  read -r -p "Type the database name ('${POSTGRES_DB}') to confirm: " typed
  if [ "$typed" != "$POSTGRES_DB" ]; then
    echo "Names did not match. Aborted, nothing was touched." >&2
    exit 1
  fi
fi

echo "Restoring $backup_file into '$POSTGRES_DB' ..."

if [ "${SMARTCAFE_NO_DOCKER:-0}" = "1" ]; then
  gunzip -c "$backup_file" | psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1
else
  gunzip -c "$backup_file" | docker compose exec -T postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1
fi

echo "Restore complete."
echo "Restart the backend, event-consumer and celery services now: they may"
echo "hold cached state (sessions, in-flight event acknowledgements) from"
echo "before the restore."
echo "  docker compose restart backend event-consumer celery celery-beat"
