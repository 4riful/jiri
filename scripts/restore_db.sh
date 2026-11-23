#!/usr/bin/env bash
set -eu

if [ "$#" -ne 1 ]; then
  printf 'Usage: %s backups/jiri-YYYYMMDD-HHMMSS.db\n' "$0" >&2
  exit 2
fi

RESTORE_SOURCE=$1
DB_PATH=${JIRI_DB_PATH:-data/jiri.db}
BACKUP_DIR=${JIRI_BACKUP_DIR:-backups}

if [ ! -f "$RESTORE_SOURCE" ]; then
  printf 'Restore source not found: %s\n' "$RESTORE_SOURCE" >&2
  exit 1
fi

mkdir -p "$BACKUP_DIR"
mkdir -p "$(dirname "$DB_PATH")"

if [ -f "$DB_PATH" ]; then
  JIRI_BACKUP_DIR="$BACKUP_DIR/pre-restore" JIRI_DB_PATH="$DB_PATH" "$(dirname "$0")/backup_db.sh" >/dev/null
fi

RESTORE_SOURCE="$RESTORE_SOURCE" DB_PATH="$DB_PATH" python3 - <<'PY'
from __future__ import annotations

import os
import sqlite3
from pathlib import Path

source_path = Path(os.environ["RESTORE_SOURCE"])
target_path = Path(os.environ["DB_PATH"])

with sqlite3.connect(source_path) as conn:
    integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
if integrity != "ok":
    raise SystemExit(f"Restore source integrity check failed: {integrity}")

with sqlite3.connect(source_path) as source, sqlite3.connect(target_path) as target:
    source.backup(target)

with sqlite3.connect(target_path) as conn:
    restored = conn.execute("PRAGMA integrity_check").fetchone()[0]
if restored != "ok":
    raise SystemExit(f"Restored database integrity check failed: {restored}")

print(f"Restored {source_path} -> {target_path}")
PY
