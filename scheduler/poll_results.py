"""Poll results for matches that should be finished by now.

§7: Query only matches with kickoff_utc + ~2h <= now and status != finished.
When a result comes back as finished: save goals (no penalties) and trigger scoring.

The scoring trigger (D3): when a match transitions to finished, compute
match_scores for all 11 players — those with predictions get scored via
scoring.quiniela.score(), those without get 0 points. One row per
player-match.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Callable

from sqlalchemy.orm import Session

from data.models import Match, MatchScore, MatchStatus, Player, Prediction
from provider.base import MatchProvider
from scoring.quiniela import score as compute_score

logger = logging.getLogger(__name__)

MATCH_WINDOW_HOURS = float(os.environ.get("POLL_WINDOW_HOURS", "2.0"))

# ── Status helpers ────────────────────────────────────────────────────────────


def _is_finished_status(status: str) -> bool:
    """Check whether a provider status string means the match is finished."""
    return status in ("finished", "FT", "AET", "PEN")


def reset_zombie_matches(session_factory: Callable[[], Session]) -> int:
    """Recupera partidos zombi: FINISHED pero sin goles registrados.

    Un partido así quedó mal finalizado (p.ej. sync lo marcó FINISHED sin
    escribir goles mientras la app dormía). poll_results filtra SCHEDULED/LIVE,
    así que nunca lo puntuaría. Lo reseteamos a SCHEDULED para que el próximo
    poll lo procese, escriba los goles y puntúe.

    Devuelve cuántos partidos se resetearon. Pensado para correr al arrancar.
    """
    session = session_factory()
    try:
        zombies = (
            session.query(Match)
            .filter(
                Match.status == MatchStatus.FINISHED,
                (Match.goals_home.is_(None)) | (Match.goals_away.is_(None)),
            )
            .all()
        )
        for m in zombies:
            logger.warning(
                "reset_zombie: %s (%s vs %s) estaba FINISHED sin goles → SCHEDULED",
                m.external_id, m.home, m.away,
            )
            m.status = MatchStatus.SCHEDULED
        session.commit()
        return len(zombies)
    finally:
        session.close()


# ── Scoring ───────────────────────────────────────────────────────────────────


def _score_match(
    session_factory: Callable[[], Session],
    *,
    match_id: int,
    goals_home: int,
    goals_away: int,
) -> int:
    """Compute and persist MatchScore rows for ALL 11 players on a finished match.

    Strategy (per §5 and §7):
      - Query every player (all 11).
      - For each player, look for a prediction on this match.
      - If a prediction exists: score(pred_home, pred_away, goals_home, goals_away).
      - If no prediction: score(None, None, …) → 0 points.
      - One MatchScore row per player-match. Idempotent: skips players who
        already have a MatchScore row for this match.

    Args:
        session_factory: Returns a new SQLAlchemy Session (e.g. SessionLocal).
        match_id: DB id of the finished match.
        goals_home: Regulation home goals (no penalties).
        goals_away: Regulation away goals (no penalties).

    Returns:
        Number of MatchScore rows inserted (0 if all players already scored).
    """
    session = session_factory()
    try:
        # Gather all players in this session
        players = session.query(Player).all()

        # Load predictions keyed by player_id
        predictions = (
            session.query(Prediction)
            .filter_by(match_id=match_id)
            .all()
        )
        pred_map: dict[int, Prediction] = {p.player_id: p for p in predictions}

        # Load existing scores to detect already-scored players (idempotency)
        existing = (
            session.query(MatchScore.player_id)
            .filter_by(match_id=match_id)
            .all()
        )
        already_scored: set[int] = {row[0] for row in existing}

        rows_inserted = 0
        for player in players:
            if player.id in already_scored:
                continue

            pred = pred_map.get(player.id)
            if pred is not None:
                points = compute_score(
                    pred_home=pred.pred_home,
                    pred_away=pred.pred_away,
                    res_home=goals_home,
                    res_away=goals_away,
                )
            else:
                points = 0  # no prediction → 0 points

            session.add(
                MatchScore(
                    player_id=player.id,
                    match_id=match_id,
                    points=points,
                )
            )
            rows_inserted += 1

        session.commit()
        return rows_inserted
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


# ── Main poll job ─────────────────────────────────────────────────────────────


async def poll_results(
    provider: MatchProvider,
    session_factory: Callable[[], Session],
    *,
    window_hours: float | None = None,
) -> dict:
    """Poll provider for results of matches whose kickoff was window_hours ago.

    Only matches with kickoff_utc + window_hours <= now and status in
    (scheduled, live) are queried. Already-finished and far-future matches
    are never polled.

    For each result whose provider status is finished:
      - saves goals_home / goals_away (regulation only, no penalties)
      - sets status = FINISHED
      - triggers _score_match for ALL 11 players (with and without predictions)

    Args:
        provider: Any MatchProvider implementation.
        session_factory: Returns a new SQLAlchemy Session (e.g. SessionLocal).
        window_hours: Hours after kickoff before polling. Defaults to
                      POLL_WINDOW_HOURS env var (2.0).

    Returns:
        dict with keys: active_matches, scored_matches, rows_inserted.
    """
    if window_hours is None:
        window_hours = MATCH_WINDOW_HOURS

    session = session_factory()
    try:
        now_utc = datetime.now(timezone.utc)
        cutoff = now_utc - timedelta(hours=window_hours)

        pending = (
            session.query(Match)
            .filter(
                Match.kickoff_utc.isnot(None),
                Match.kickoff_utc <= cutoff,
                Match.status.in_([MatchStatus.SCHEDULED, MatchStatus.LIVE]),
            )
            .all()
        )

        if not pending:
            logger.debug("No pending matches to poll (cutoff=%s)", cutoff.isoformat())
            return {"active_matches": 0, "scored_matches": 0, "rows_inserted": 0}

        external_ids = [m.external_id for m in pending]
        logger.info("Polling %d matches: %s", len(pending), external_ids)

        results = await provider.fetch_results(external_ids)
        result_map: dict[str, object] = {r.external_id: r for r in results}  # type: ignore[dict-item]

        scored_matches = 0
        rows_inserted = 0

        for match in pending:
            result = result_map.get(match.external_id)
            if result is None:
                continue

            # ProviderResult has .status (str) and .home_goals/.away_goals (int)
            r_status: str = result.status  # type: ignore[union-attr]
            r_home: int = result.home_goals  # type: ignore[union-attr]
            r_away: int = result.away_goals  # type: ignore[union-attr]

            if _is_finished_status(r_status):
                match.goals_home = r_home
                match.goals_away = r_away
                match.status = MatchStatus.FINISHED
                session.commit()  # flush match state before scoring (needs players in fresh session)

                n = _score_match(
                    session_factory,
                    match_id=match.id,
                    goals_home=r_home,
                    goals_away=r_away,
                )
                scored_matches += 1
                rows_inserted += n
                logger.info(
                    "Match %s finished: %s %d-%d %s → %d players scored",
                    match.external_id,
                    match.home,
                    match.goals_home,
                    match.goals_away,
                    match.away,
                    n,
                )

            elif r_status in ("cancelled",):
                match.status = MatchStatus.CANCELLED
                session.commit()
                logger.info("Match %s cancelled", match.external_id)

            # live / scheduled matches stay as-is — provider hasn't finished them yet

        return {
            "active_matches": len(pending),
            "scored_matches": scored_matches,
            "rows_inserted": rows_inserted,
        }
    finally:
        session.close()
