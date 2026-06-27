#!/usr/bin/env python3
"""Seed script — populates the database with sample data.

Usage:
    uv run python scripts/seed.py          # full seed
    uv run python scripts/seed.py --reset  # drop + recreate + seed
    uv run python scripts/seed.py --verify # count rows
"""

import sys
import os
from datetime import datetime, date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data.database import init_db, session_scope
from data.models import Player, Match, Prediction, MatchScore, StandingsSnapshot, MatchStatus


# ── Sample data ──────────────────────────────────────────────────

PLAYERS = [
    {"name": "Carlos",  "password": "abc123", "avatar_flag": "🇸🇻", "is_setup": True},
    {"name": "Diana",   "password": "xyz789", "avatar_flag": "🇸🇻", "is_setup": True},
    {"name": "Mario",   "password": "qwe456", "avatar_flag": "🇲🇽", "is_setup": False},
    {"name": "Lucía",   "password": "asd321", "avatar_flag": "🇦🇷", "is_setup": False},
]

MATCHES = [
    {"external_id": "fifwc-group-a-01", "home": "🇶🇦 Qatar",       "away": "🇪🇨 Ecuador",
     "kickoff_utc": datetime(2026, 6, 11, 16, 0), "match_date_local": date(2026, 6, 11),
     "stage": "group", "status": MatchStatus.SCHEDULED},
    {"external_id": "fifwc-group-a-02", "home": "🇸🇳 Senegal",     "away": "🇳🇱 Netherlands",
     "kickoff_utc": datetime(2026, 6, 11, 19, 0), "match_date_local": date(2026, 6, 11),
     "stage": "group", "status": MatchStatus.SCHEDULED},
    {"external_id": "fifwc-group-b-01", "home": "🏴 England",      "away": "🇮🇷 Iran",
     "kickoff_utc": datetime(2026, 6, 12, 13, 0), "match_date_local": date(2026, 6, 12),
     "stage": "group", "status": MatchStatus.SCHEDULED},
    {"external_id": "fifwc-group-b-02", "home": "🇺🇸 USA",          "away": "🇼🇸 Wales",
     "kickoff_utc": datetime(2026, 6, 12, 19, 0), "match_date_local": date(2026, 6, 12),
     "stage": "group", "status": MatchStatus.FINISHED,
     "goals_home": 1, "goals_away": 1},
    {"external_id": "fifwc-group-c-01", "home": "🇦🇷 Argentina",    "away": "🇸🇦 Saudi Arabia",
     "kickoff_utc": datetime(2026, 6, 13, 10, 0), "match_date_local": date(2026, 6, 13),
     "stage": "group", "status": MatchStatus.FINISHED,
     "goals_home": 2, "goals_away": 1},
    {"external_id": "fifwc-group-c-02", "home": "🇲🇽 Mexico",       "away": "🇵🇱 Poland",
     "kickoff_utc": datetime(2026, 6, 13, 16, 0), "match_date_local": date(2026, 6, 13),
     "stage": "group", "status": MatchStatus.LIVE,
     "goals_home": 0, "goals_away": 0},
    # TBD teams (home/away null)
    {"external_id": "fifwc-group-d-01", "home": None, "away": None,
     "kickoff_utc": datetime(2026, 6, 14, 13, 0), "match_date_local": date(2026, 6, 14),
     "stage": "group", "status": MatchStatus.SCHEDULED},
    {"external_id": "fifwc-group-d-02", "home": None, "away": None,
     "kickoff_utc": datetime(2026, 6, 14, 19, 0), "match_date_local": date(2026, 6, 14),
     "stage": "group", "status": MatchStatus.SCHEDULED},
]

# predictions: (player_index, match_index, pred_home, pred_away)
PREDICTIONS = [
    # Carlos predicts all 8 matches
    (0, 0, 2, 0), (0, 1, 0, 2), (0, 2, 3, 0), (0, 3, 1, 1),
    (0, 4, 2, 0), (0, 5, 1, 0), (0, 6, 2, 1), (0, 7, 1, 2),
    # Diana predicts 6 matches
    (1, 0, 1, 1), (1, 1, 0, 3), (1, 2, 2, 0), (1, 3, 2, 1),
    (1, 4, 3, 0), (1, 5, 1, 1),
    # Mario predicts 4 matches
    (2, 0, 2, 1), (2, 2, 1, 0), (2, 4, 1, 0), (2, 6, 3, 0),
]

# match_scores: (player_index, match_index, points) — only for finished matches
MATCH_SCORES = [
    (0, 3, 2),  # Carlos got 2 pts for USA-Wales
    (0, 4, 3),  # Carlos got 3 pts for ARG-KSA
    (1, 3, 1),  # Diana got 1 pt
    (1, 4, 2),  # Diana got 2 pts
]

# standings snapshots
STANDINGS_SNAPSHOTS = [
    {"player_idx": 0, "date": date(2026, 6, 13), "total_points": 5, "rank": 1},
    {"player_idx": 1, "date": date(2026, 6, 13), "total_points": 3, "rank": 2},
    {"player_idx": 2, "date": date(2026, 6, 13), "total_points": 0, "rank": 3},
    {"player_idx": 3, "date": date(2026, 6, 13), "total_points": 0, "rank": 3},
]


def seed():
    """Insert all sample data."""
    args = sys.argv[1:]

    if "--reset" in args:
        init_db(drop_all=True)

    with session_scope() as session:
        # Players
        players = []
        for p in PLAYERS:
            player = Player(**p)
            session.add(player)
            players.append(player)
        session.flush()  # get IDs
        print(f"✅ {len(players)} players inserted")

        # Matches
        matches = []
        for m in MATCHES:
            match = Match(**m)
            session.add(match)
            matches.append(match)
        session.flush()
        print(f"✅ {len(matches)} matches inserted")

        # Predictions
        pred_count = 0
        for pi, mi, ph, pa in PREDICTIONS:
            pred = Prediction(
                player_id=players[pi].id,
                match_id=matches[mi].id,
                pred_home=ph,
                pred_away=pa,
            )
            session.add(pred)
            pred_count += 1
        print(f"✅ {pred_count} predictions inserted")

        # Match Scores
        score_count = 0
        for pi, mi, pts in MATCH_SCORES:
            score = MatchScore(
                player_id=players[pi].id,
                match_id=matches[mi].id,
                points=pts,
            )
            session.add(score)
            score_count += 1
        print(f"✅ {score_count} match scores inserted")

        # Standings Snapshots
        snap_count = 0
        for s in STANDINGS_SNAPSHOTS:
            snap = StandingsSnapshot(
                player_id=players[s["player_idx"]].id,
                snapshot_date_local=s["date"],
                total_points=s["total_points"],
                rank=s["rank"],
            )
            session.add(snap)
            snap_count += 1
        print(f"✅ {snap_count} standings snapshots inserted")

        # ── Quick read-back to verify to_dict() works (no DetachedInstanceError) ──
        first_player = session.get(Player, players[0].id)
        d = first_player.to_dict()
        assert d["name"] == "Carlos", f"Expected Carlos, got {d['name']}"
        print(f"✅ to_dict() verified: {d['name']} → {d}")

    print("\n🎉 Seed complete! Database is ready.")


if __name__ == "__main__":
    if "--verify" in sys.argv:
        from data.database import SessionLocal
        from sqlalchemy import text
        with SessionLocal() as session:
            tables = ["players", "matches", "predictions", "match_scores", "standings_snapshots"]
            for t in tables:
                count = session.execute(text(f"SELECT COUNT(*) FROM {t}")).scalar()
                print(f"  {t}: {count} rows")
    else:
        seed()
