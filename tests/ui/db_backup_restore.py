#!/usr/bin/env python3
"""
Backup and restore the databases touched by add_test_shelves.py.

Backups are plain copies of the database files, stored alongside the originals
with a timestamp suffix (e.g. app.db.bak.20250528_143012).

Usage:
    # Commands (will prompt for config folder path):
    python3 tests/ui/db_backup_restore.py backup
    python3 tests/ui/db_backup_restore.py list
    python3 tests/ui/db_backup_restore.py restore
    python3 tests/ui/db_backup_restore.py clean

    # Skip the prompt by supplying the path directly:
    python3 tests/ui/db_backup_restore.py restore --config /path/to/config
    python3 tests/ui/db_backup_restore.py restore --config /path/to/config --backup app.db.bak.20250528_143012

The script expects app.db inside the given config folder.
Backups are stored alongside app.db with a timestamp suffix (e.g. app.db.bak.20250528_143012).
"""

import argparse
import shutil
from datetime import datetime
from pathlib import Path

BACKUP_SUFFIX = ".bak"


def backup_path_for(db: Path, tag: str) -> Path:
    return db.parent / f"{db.name}{BACKUP_SUFFIX}.{tag}"


def find_backups(db: Path) -> list[Path]:
    pattern = f"{db.name}{BACKUP_SUFFIX}.*"
    return sorted(db.parent.glob(pattern))


def cmd_backup(db: Path) -> None:
    if not db.exists():
        raise SystemExit(f"Database not found: {db}")
    tag = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = backup_path_for(db, tag)
    shutil.copy2(db, dest)
    print(f"Backed up: {db} -> {dest}")


def cmd_list(db: Path) -> None:
    backups = find_backups(db)
    if not backups:
        print(f"No backups found for {db}")
        return
    print(f"Backups for {db}:")
    for i, p in enumerate(backups):
        marker = " (latest)" if i == len(backups) - 1 else ""
        print(f"  {p.name}{marker}")


def cmd_restore(db: Path, backup_name: str | None) -> None:
    if backup_name:
        src = db.parent / backup_name
        if not src.exists():
            raise SystemExit(f"Backup not found: {src}")
    else:
        backups = find_backups(db)
        if not backups:
            raise SystemExit(f"No backups found for {db}")
        src = backups[-1]

    if not db.exists():
        print(f"Note: {db} does not exist; creating from backup.")
    shutil.copy2(src, db)
    print(f"Restored: {src} -> {db}")


def cmd_clean(db: Path) -> None:
    backups = find_backups(db)
    if not backups:
        print(f"No backups found for {db}")
        return
    for p in backups:
        p.unlink()
        print(f"Deleted: {p.name}")
    print(f"Removed {len(backups)} backup(s).")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=["backup", "restore", "list", "clean"])
    parser.add_argument("--config", default=None, metavar="DIR",
                        help="Path to config folder containing app.db (skips the prompt)")
    parser.add_argument(
        "--backup",
        metavar="FILENAME",
        default=None,
        help="Backup filename to restore (default: most recent). Only used with 'restore'.",
    )
    args = parser.parse_args()

    if args.config:
        config_dir = Path(args.config)
    else:
        raw = input("Path to config folder: ").strip()
        if not raw:
            raise SystemExit("Config folder path is required.")
        config_dir = Path(raw)

    db = config_dir / "app.db"

    if args.command == "backup":
        cmd_backup(db)
    elif args.command == "restore":
        cmd_restore(db, args.backup)
    elif args.command == "list":
        cmd_list(db)
    elif args.command == "clean":
        cmd_clean(db)


if __name__ == "__main__":
    main()
