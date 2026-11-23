#!/usr/bin/env bash
set -eu
DB_PATH=${JIRI_DB_PATH:-data/jiri.db}
BACKUP_DIR=${JIRI_BACKUP_DIR:-backups}

if [ ! -f "$DB_PATH" ]; then
  printf 'Database not found: %s\n' "$DB_PATH" >&2
  exit 1
fi

mkdir -p "$BACKUP_DIR"
STAMP=$(date +%Y%m%d-%H%M%S)
BACKUP_PATH="$BACKUP_DIR/jiri-$STAMP.db"
MANIFEST_PATH="$BACKUP_PATH.manifest.json"

DB_PATH="$DB_PATH" BACKUP_PATH="$BACKUP_PATH" MANIFEST_PATH="$MANIFEST_PATH" python3 - <<'PY'
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from pathlib import Path

source_path = Path(os.environ["DB_PATH"])
backup_path = Path(os.environ["BACKUP_PATH"])
manifest_path = Path(os.environ["MANIFEST_PATH"])


def _quote_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'

with sqlite3.connect(source_path) as source, sqlite3.connect(backup_path) as backup:
    source.backup(backup)

with sqlite3.connect(backup_path) as conn:
    integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
    schema_row = conn.execute("SELECT value FROM settings WHERE key = 'schema_version'").fetchone()
    tables = [row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name")]
    counts = {table: conn.execute(f"SELECT COUNT(*) FROM {_quote_identifier(table)}").fetchone()[0] for table in tables}

if integrity != "ok":
    backup_path.unlink(missing_ok=True)
    raise SystemExit(f"Backup integrity check failed: {integrity}")

digest = hashlib.sha256(backup_path.read_bytes()).hexdigest()
manifest = {
    "source": str(source_path),
    "backup": str(backup_path),
    "sha256": digest,
    "schema_version": schema_row[0] if schema_row else None,
    "tables": tables,
    "row_counts": counts,
    "integrity_check": integrity,
}
manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
print(str(backup_path))
PY
