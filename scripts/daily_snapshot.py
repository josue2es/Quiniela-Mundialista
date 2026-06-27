#!/usr/bin/env python3
"""Daily snapshot: one row per player per day with total_points and rank.

Runs at 00:00 America/El_Salvador via Hermes cron.
Computes total_points by summing match_scores.points per player,
assigns competition rank (ties share rank, next skips),
inserts into standings_snapshots.

Idempotent: deletes existing snapshots for snapshot_date_local before re-inserting,
so re-running on the same day is safe.
"""

import sys
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

# ── Project setup ────────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from data.database import SessionLocal, init_db  # noqa: E402
from data.models import MatchScore, StandingsSnapshot  # noqa: E402

TZ_ES = ZoneInfo("America/El_Salvador")


def compute_standings():
    """Return list of (player_id, total_points, rank) sorted by points desc.

    Competition rank: tied players share the same rank, and the next distinct
    score skips positions accordingly (1, 2, 2, 4, ...).
    """
    from sqlalchemy import func

    with SessionLocal() as session:
        rows = (
            session.query(
                MatchScore.player_id,
                func.sum(MatchScore.points).label("total_points"),
            )
            .group_by(MatchScore.player_id)
            .order_by(func.sum(MatchScore.points).desc())
            .all()
        )

    if not rows:
        return []

    standings = []
    rank = 0
    prev_points = None
    position = 0

    for player_id, total_points in rows:
        position += 1
        if total_points != prev_points:
            rank = position
        standings.append((player_id, total_points or 0, rank))
        prev_points = total_points

    return standings


def take_snapshot():
    """Compute standings and insert snapshots for today (ES date)."""
    today_es = datetime.now(TZ_ES).date()

    standings = compute_standings()

    with SessionLocal() as session:
        # Delete existing snapshots for today (idempotency)
        deleted = (
            session.query(StandingsSnapshot)
            .filter(StandingsSnapshot.snapshot_date_local == today_es)
            .delete()
        )
        if deleted:
            print(f"daily_snapshot: replaced {deleted} existing snapshot(s) for {today_es}", file=sys.stderr)

        if standings:
            for player_id, total_points, rank in standings:
                session.add(
                    StandingsSnapshot(
                        player_id=player_id,
                        snapshot_date_local=today_es,
                        total_points=total_points,
                        rank=rank,
                    )
                )
            print(
                f"daily_snapshot: inserted {len(standings)} snapshot(s) for {today_es}",
                file=sys.stderr,
            )
        else:
            print(f"daily_snapshot: no match_scores yet for {today_es}", file=sys.stderr)

        session.commit()


if __name__ == "__main__":
    try:
        init_db()  # Ensure tables exist (safe to call repeatedly)
        take_snapshot()
    except Exception as e:
        print(f"daily_snapshot ERROR: {e}", file=sys.stderr)
        raise
