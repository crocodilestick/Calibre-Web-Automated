#!/usr/bin/env python3
"""
Add test shelves and magic shelves to app.db for UI layout testing.

Usage:
    # Prompted for config folder path:
    python3 tests/ui/add_test_shelves.py

    # Skip the prompt by supplying the path directly:
    python3 tests/ui/add_test_shelves.py --config /path/to/config

    # Target a specific user and count:
    python3 tests/ui/add_test_shelves.py --config /path/to/config --user admin --count 20

The script expects app.db inside the given config folder.

Name generation:
    Each shelf name is built from 2-3 random words (10% chance of 6 words).
    ~10% of shelves and magic shelves are marked public.

To undo: use tests/ui/db_backup_restore.py to restore a backup taken before running.
"""

import argparse
import json
import random
import uuid
from datetime import datetime, timezone
from pathlib import Path

try:
    import sqlalchemy
    from sqlalchemy import create_engine, text
    from sqlalchemy.orm import sessionmaker
except ImportError:
    raise SystemExit("sqlalchemy is required: pip install sqlalchemy")

# ---------------------------------------------------------------------------
# Word pool — 64 words used to generate random shelf names
# ---------------------------------------------------------------------------
WORDS = [
    # Adjectives
    "Ancient", "Forgotten", "Crimson", "Wandering",
    "Silver", "Hollow", "Borrowed", "Distant",
    "Golden", "Quiet", "Twisted", "Endless",
    "Broken", "Velvet", "Stormy", "Pale",
    "Faded", "Moonlit", "Sunken", "Frosted",
    "Burning", "Cobalt", "Ruined", "Luminous",
    "Tangled", "Dreaming", "Scarlet", "Whispered",
    "Hidden", "Savage", "Fleeting", "Ashen",
    # Nouns
    "Tower", "Library", "Garden", "Abyss",
    "Chronicle", "Ember", "Horizon", "Labyrinth",
    "Mirror", "Phantom", "Relic", "Tempest",
    "Archive", "Lantern", "Codex", "Threshold",
    "Vault", "Throne", "Wanderer", "Oracle",
    "Memoir", "Requiem", "Cascade", "Solstice",
    "Bastion", "Hollow", "Specter", "Meridian",
    "Epoch", "Canticle", "Shard", "Reverie",
]

MAGIC_ICONS = [
    "📚", "📖", "⭐", "🌟", "✨", "🔥", "🎯", "🏆",
    "❤️", "💙", "💚", "💛", "🚀", "🔮", "👑", "🎭",
    "🌈", "🐉", "🎓", "🌸",
]


def random_name(words: list[str]) -> str:
    count = 6 if random.random() < 0.1 else random.randint(2, 3)
    chosen = random.sample(words, count)
    return " ".join(chosen)


def get_user_id(conn, username: str | None) -> int:
    if username:
        row = conn.execute(
            text("SELECT id FROM user WHERE name = :name"), {"name": username}
        ).fetchone()
        if row is None:
            available = [r[0] for r in conn.execute(text("SELECT name FROM user ORDER BY id")).fetchall()]
            raise SystemExit(f"User {username!r} not found. Available users: {available}")
    else:
        row = conn.execute(text("SELECT id FROM user ORDER BY id LIMIT 1")).fetchone()
        if row is None:
            raise SystemExit("No users found in app.db — is this the right database?")
    return row[0]


def is_public_roll() -> int:
    return 1 if random.random() < 0.1 else 0


def add_shelves(conn, user_id: int, count: int) -> list[str]:
    names = []
    for _ in range(count):
        name = random_name(WORDS)
        public = is_public_roll()
        conn.execute(
            text(
                "INSERT INTO shelf (uuid, name, is_public, user_id, kobo_sync, created, last_modified)"
                " VALUES (:uuid, :name, :public, :user_id, 0, :now, :now)"
            ),
            {"uuid": str(uuid.uuid4()), "name": name, "public": public,
             "user_id": user_id, "now": datetime.now(timezone.utc).isoformat()},
        )
        names.append(f"{name}{' (Public)' if public else ''}")
    return names


def add_magic_shelves(conn, user_id: int, count: int) -> list[str]:
    icons = random.sample(MAGIC_ICONS, min(count, len(MAGIC_ICONS)))
    while len(icons) < count:
        icons.append(random.choice(MAGIC_ICONS))

    names = []
    for icon in icons[:count]:
        name = random_name(WORDS)
        public = is_public_roll()
        conn.execute(
            text(
                "INSERT INTO magic_shelf"
                " (uuid, name, is_public, is_system, user_id, icon, rules, kobo_sync, created, last_modified)"
                " VALUES (:uuid, :name, :public, 0, :user_id, :icon, :rules, 0, :now, :now)"
            ),
            {
                "uuid": str(uuid.uuid4()),
                "name": name,
                "public": public,
                "user_id": user_id,
                "icon": icon,
                "rules": json.dumps({}),
                "now": datetime.now(timezone.utc).isoformat(),
            },
        )
        names.append(f"{icon} {name}{' (Public)' if public else ''}")
    return names


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", default=None, metavar="DIR",
                        help="Path to config folder containing app.db (skips the prompt)")
    parser.add_argument("--user", default=None,
                        help="Username to create shelves for (default: first user in db)")
    parser.add_argument("--count", type=int, default=10,
                        help="Number of each type to create (default: 10)")
    args = parser.parse_args()

    if args.config:
        config_dir = Path(args.config)
    else:
        raw = input("Path to config folder: ").strip()
        if not raw:
            raise SystemExit("Config folder path is required.")
        config_dir = Path(raw)

    db_path = config_dir / "app.db"
    if not db_path.exists():
        raise SystemExit(f"Database not found: {db_path}")

    engine = create_engine(f"sqlite:///{db_path}", echo=False)

    with engine.begin() as conn:
        user_id = get_user_id(conn, args.user)
        print(f"Using user_id={user_id}, db={db_path}")

        shelf_names = add_shelves(conn, user_id, args.count)
        print(f"\nAdded {len(shelf_names)} shelves:")
        for n in shelf_names:
            print(f"  {n}")

        magic_names = add_magic_shelves(conn, user_id, args.count)
        print(f"\nAdded {len(magic_names)} magic shelves:")
        for n in magic_names:
            print(f"  {n}")

    print("\nDone. Restart the server to see changes.")


if __name__ == "__main__":
    main()
