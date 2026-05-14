#!/usr/bin/env bash
set -eu
DB_PATH=${JIRI_DB_PATH:-data/jiri.db}
BACKUP_DIR=${JIRI_BACKUP_DIR:-backups}
mkdir -p "$BACKUP_DIR"
cp "$DB_PATH" "$BACKUP_DIR/jiri-$(date +%Y%m%d-%H%M%S).db"
