# Safe Update Methodology

Status: design rule and operational checklist. Automatic updating must remain opt-in until this process passes real Pi smoke testing.

## Goals

- Detect a newer GitHub build, branch head, or release without modifying the app.
- Back up SQLite before any code changes or migrations run.
- Verify backup integrity and row counts before continuing.
- Apply updates only with a fast-forward or signed release artifact flow.
- Run schema migration and health checks after update.
- Restore the previous database if validation fails.
- Avoid destructive Git actions during normal checks.

## Non-Goals

- No blind `git pull` from the UI.
- No force reset as the default update path.
- No database migration before a verified backup exists.
- No AI-controlled update or restore decisions.

## Update Channels

1. **Check only**: dashboard `Updates` button uses the Git remote SHA check and never modifies files.
2. **Manual safe update**: operator checks the dashboard, backs up DB, stops services, applies the update, runs smoke tests, then restarts services.
3. **Future opt-in auto-update**: a systemd timer may run only after Stage Pi smoke acceptance. It must use the same backup, integrity, and rollback rules.

## GitHub Detection Rule

- For branch builds, compare local `HEAD` with the upstream branch using `git ls-remote`.
- For release builds, compare the installed version with the latest GitHub release tag using GitHub's release API or `gh release view` if `gh` is installed.
- Detection must not run `git pull`, `git reset`, or write to SQLite.
- The current implementation covers branch SHA checks through `src/jiri/update_checker.py` and the dashboard `Updates` button.

## Pre-Update Database Protection

Before any update is applied:

1. Stop JIRI services that may write to SQLite.
2. Run `scripts/backup_db.sh`.
3. Require `PRAGMA integrity_check = ok` on the backup.
4. Write a backup manifest containing SHA-256, schema version, table names, and row counts.
5. Keep the backup under `JIRI_BACKUP_DIR` or `backups/` by default.
6. Do not continue if the backup or manifest step fails.

The backup script uses SQLite's online backup API, not a raw file copy.

## Apply Update Rule

Branch update path:

1. Record current Git SHA.
2. Fetch the configured upstream branch.
3. Apply only if fast-forward is possible.
4. Never force-push, force-reset, or rebase from the update job.

Release update path:

1. Download the release artifact or tag.
2. Verify checksum if one is published.
3. Install into a staged directory.
4. Swap service target only after smoke checks pass.

## Post-Update Verification

After code updates and before service restart is considered successful:

1. Run `python3 -m compileall src`.
2. Run `python3 -c "from jiri import db; db.init_db()"` with the production DB path.
3. Run `PRAGMA integrity_check` on the migrated DB.
4. Run a lightweight smoke test: health snapshot, DB row counts, weather cache read, persona settings read.
5. Restart services only after checks pass.

## Restore Rule

If migration or smoke checks fail:

1. Stop JIRI services.
2. Use `scripts/restore_db.sh <backup-file>`.
3. Verify restored DB integrity.
4. Return code to the previous known-good SHA or staged release.
5. Restart services only after health checks pass.

`scripts/restore_db.sh` backs up the current DB into `backups/pre-restore/` before replacing it.

## Timely Backup Policy

- Pre-update backup: mandatory before every update.
- Scheduled backup: daily on the Pi once systemd deployment is accepted.
- Retention target: keep at least 7 daily backups and 4 weekly backups.
- Backup location: local `backups/` first; optional external sync later.
- Restore drills: test restore on a copied DB before trusting auto-update.

## Systemd Timer Sketch

This is not enabled by default:

```text
jiri-backup.timer      daily SQLite backup
jiri-update-check.timer hourly check-only update status
jiri-safe-update.timer optional, disabled until explicitly enabled
```

The auto-update timer must stay disabled until the real Pi update/restore smoke test is passed.

## Acceptance Checklist

- `scripts/backup_db.sh` creates a DB and manifest.
- Manifest SHA-256 matches the backup file.
- Restore from backup works on a copied DB.
- Update check detects newer remote SHA without modifying files.
- A failed migration restores DB successfully.
- Service restart works after restore.
- User data tables retain expected row counts after update and restore.
