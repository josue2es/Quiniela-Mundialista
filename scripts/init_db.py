#!/usr/bin/env python3
"""Migration script — creates all tables in quiniela.db.

Usage:
    uv run python scripts/init_db.py          # create tables
    uv run python scripts/init_db.py --reset  # drop + recreate
    uv run python scripts/init_db.py --verify # check all tables exist
"""

import sys
import os

# Ensure project root is on path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data.database import init_db, engine, DB_PATH
from data.models import Base
from sqlalchemy import inspect


def verify_tables() -> bool:
    """Check that all expected tables exist."""
    inspector = inspect(engine)
    existing = set(inspector.get_table_names())
    expected = {"players", "matches", "predictions", "match_scores", "standings_snapshots"}
    missing = expected - existing
    if missing:
        print(f"❌ Missing tables: {missing}")
        return False
    print(f"✅ All {len(expected)} tables present: {sorted(expected)}")
    return True


def main():
    args = sys.argv[1:]

    if "--verify" in args:
        print(f"Database: {DB_PATH}")
        ok = verify_tables()
        sys.exit(0 if ok else 1)

    drop_all = "--reset" in args
    action = "DROP + CREATE" if drop_all else "CREATE"

    print(f"Database: {DB_PATH}")
    print(f"Action:   {action}")
    init_db(drop_all=drop_all)
    print("✅ Migration complete.")

    # Auto-verify
    verify_tables()


if __name__ == "__main__":
    main()
