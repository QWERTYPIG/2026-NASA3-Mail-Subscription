#!/usr/bin/env bash
set -euo pipefail

load_env_file() {
  local file_path="$1"
  [[ -z "$file_path" || ! -f "$file_path" ]] && return 0
  while IFS= read -r line; do
    [[ -z "$line" || "$line" =~ ^[[:space:]]*# ]] && continue
    if [[ "$line" =~ ^[A-Za-z_][A-Za-z0-9_]*= ]]; then
      export "$line"
    fi
  done < "$file_path"
}

# Load base env, then role overrides.
ENV_FILE=${ENV_FILE:-.env}
ENV_ROLE=${ENV_ROLE:-.env.role}
load_env_file "$ENV_FILE"
load_env_file "$ENV_ROLE"

DB_NAME=${DB_NAME:-Subscriptions}
DB_USER=${DB_USER:-MailAdmin}
DB_PASSWORD=${DB_PASSWORD:-password}
PRIMARY_HOST=${DB_HOST:-}
LAST_SYNC_FILE=${LAST_SYNC_FILE:-}

if [[ -z "$PRIMARY_HOST" ]]; then
  echo "DB_HOST is not set. Provide it in .env or the environment." >&2
  exit 1
fi

DEFAULT_REPLICA_HOSTS="172.16.127.102,172.16.127.116,172.16.127.117"
REPLICA_HOSTS=${DB_REPLICA_HOSTS:-$DEFAULT_REPLICA_HOSTS}

if ! command -v pg_dump >/dev/null || ! command -v pg_restore >/dev/null || ! command -v psql >/dev/null; then
  echo "pg_dump, pg_restore, and psql must be installed on this machine." >&2
  exit 1
fi

DUMP_FILE=$(mktemp -t mailsub_pg_dump_XXXXXX.dump)
trap 'rm -f "$DUMP_FILE"' EXIT

export PGPASSWORD="$DB_PASSWORD"

pg_dump \
  --host "$PRIMARY_HOST" \
  --username "$DB_USER" \
  --format=custom \
  --file "$DUMP_FILE" \
  "$DB_NAME"

IFS="," read -r -a HOSTS <<< "$REPLICA_HOSTS"
for host in "${HOSTS[@]}"; do
  host=$(echo "$host" | xargs)
  [[ -z "$host" ]] && continue
  if [[ "$host" == "$PRIMARY_HOST" ]]; then
    continue
  fi

  psql --host "$host" --username "$DB_USER" --dbname "$DB_NAME" -c "SELECT 1" >/dev/null

  pg_restore \
    --host "$host" \
    --username "$DB_USER" \
    --dbname "$DB_NAME" \
    --clean \
    --if-exists \
    --no-owner \
    --no-privileges \
    "$DUMP_FILE"

done

if [[ -n "$LAST_SYNC_FILE" ]]; then
  mkdir -p "$(dirname "$LAST_SYNC_FILE")"
  date +%s > "$LAST_SYNC_FILE"
fi

unset PGPASSWORD
