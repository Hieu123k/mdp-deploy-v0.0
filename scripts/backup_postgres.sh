#!/usr/bin/env sh
set -eu

ROOT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
ENV_FILE="$ROOT_DIR/.env.production"
COMPOSE_FILE="$ROOT_DIR/docker-compose.prod.yml"

if [ -f "$ENV_FILE" ]; then
    set -a
    . "$ENV_FILE"
    set +a
else
    echo "Warning: .env.production was not found. Falling back to current environment."
fi

: "${POSTGRES_DB:=mdp}"
: "${POSTGRES_USER:=mdp_user}"

mkdir -p "$ROOT_DIR/backups"

TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
BACKUP_FILE="$ROOT_DIR/backups/${POSTGRES_DB}_${TIMESTAMP}.dump"

if [ -f "$ENV_FILE" ]; then
    docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE" exec -T postgres \
        pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc > "$BACKUP_FILE"
else
    docker compose -f "$COMPOSE_FILE" exec -T postgres \
        pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc > "$BACKUP_FILE"
fi

echo "Backup written to $BACKUP_FILE"
