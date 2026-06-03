#!/usr/bin/env sh
set -eu

if [ "$#" -ne 1 ]; then
    echo "Usage: ./scripts/restore_postgres.sh backups/<file>.dump"
    exit 1
fi

ROOT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
ENV_FILE="$ROOT_DIR/.env.production"
COMPOSE_FILE="$ROOT_DIR/docker-compose.prod.yml"
BACKUP_FILE="$1"

if [ ! -f "$BACKUP_FILE" ] && [ -f "$ROOT_DIR/$BACKUP_FILE" ]; then
    BACKUP_FILE="$ROOT_DIR/$BACKUP_FILE"
fi

if [ ! -f "$BACKUP_FILE" ]; then
    echo "Backup file not found: $1"
    exit 1
fi

if [ -f "$ENV_FILE" ]; then
    set -a
    . "$ENV_FILE"
    set +a
else
    echo "Warning: .env.production was not found. Falling back to current environment."
fi

: "${POSTGRES_DB:=mdp}"
: "${POSTGRES_USER:=mdp_user}"

echo "Warning: restoring $BACKUP_FILE may overwrite data in database $POSTGRES_DB."

if [ -f "$ENV_FILE" ]; then
    docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE" exec -T postgres \
        pg_restore --clean --if-exists -U "$POSTGRES_USER" -d "$POSTGRES_DB" < "$BACKUP_FILE"
else
    docker compose -f "$COMPOSE_FILE" exec -T postgres \
        pg_restore --clean --if-exists -U "$POSTGRES_USER" -d "$POSTGRES_DB" < "$BACKUP_FILE"
fi

echo "Restore completed from $BACKUP_FILE"
