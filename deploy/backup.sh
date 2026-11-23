#!/usr/bin/env sh
# Respaldo diario: base de datos + adjuntos. Programar con cron, p. ej.:
#   0 2 * * * cd /opt/gestiona && ./deploy/backup.sh >> backups/backup.log 2>&1
set -eu
STAMP=$(date +%Y%m%d-%H%M)
DEST=${BACKUP_DIR:-./backups}
KEEP_DAYS=${KEEP_DAYS:-14}
mkdir -p "$DEST"

docker compose --env-file .env.production exec -T postgres \
  pg_dump -U gestiona -d gestiona -Fc > "$DEST/db-$STAMP.dump"

docker compose --env-file .env.production run --rm -T --no-deps --entrypoint sh backend \
  -c "tar -C /app -czf - media" > "$DEST/media-$STAMP.tgz"

find "$DEST" -name 'db-*.dump' -mtime +"$KEEP_DAYS" -delete
find "$DEST" -name 'media-*.tgz' -mtime +"$KEEP_DAYS" -delete
echo "$(date -Is) backup ok: $DEST/db-$STAMP.dump"

# Restaurar:
#   docker compose exec -T postgres pg_restore -U gestiona -d gestiona --clean < backups/db-XXXX.dump
