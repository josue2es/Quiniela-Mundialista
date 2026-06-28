"""Tab 2 'Tabla' — Standings with +hoy and Δpos vs yesterday's snapshot.

§9: Standings desc por total_points. Columnas: posición, avatar(bandera),
nombre, total, +hoy (suma match_scores de partidos con match_date_local == hoy),
Δpos (flecha ↑/↓ vs snapshot de ayer = snapshot(ayer).rank − rank_actual).
"""

from datetime import date, datetime
from zoneinfo import ZoneInfo

from nicegui import ui
from sqlalchemy import func

from data.database import SessionLocal
from data.models import Match, MatchScore, StandingsSnapshot, Player

TZ_ES = ZoneInfo("America/El_Salvador")


def _today_es() -> date:
    return datetime.now(TZ_ES).date()


def _compute_standings():
    """Return list of {
        player_id, player_name, avatar_flag, total_points, rank,
        hoy_points, yesterday_rank,
    } sorted by total_points desc, competition rank (ties share rank)."""
    today = _today_es()

    with SessionLocal() as session:
        # ── Current standings: SUM(points) per player ──
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

        player_ids = [r.player_id for r in rows]

        # ── Player info ──
        players_map = {
            p.id: p
            for p in session.query(Player).filter(Player.id.in_(player_ids)).all()
        }

        # ── +hoy: SUM(points) for matches whose match_date_local == today ──
        hoy_rows = dict(
            session.query(
                MatchScore.player_id,
                func.sum(MatchScore.points).label("hoy_points"),
            )
            .join(Match, MatchScore.match_id == Match.id)
            .filter(Match.match_date_local == today)
            .group_by(MatchScore.player_id)
            .all()
        )

        # ── Yesterday's snapshot ──
        most_recent_snapshot_date = (
            session.query(func.max(StandingsSnapshot.snapshot_date_local))
            .filter(StandingsSnapshot.snapshot_date_local < today)
            .scalar()
        )

        yesterday_ranks = {}
        if most_recent_snapshot_date is not None:
            snaps = (
                session.query(StandingsSnapshot)
                .filter(
                    StandingsSnapshot.snapshot_date_local
                    == most_recent_snapshot_date
                )
                .all()
            )
            yesterday_ranks = {s.player_id: s.rank for s in snaps}

    # ── Assign competition rank (ties share rank) ──
    standings = []
    rank = 0
    prev_points = None
    position = 0

    for player_id, total_points in rows:
        position += 1
        if total_points != prev_points:
            rank = position
        player = players_map.get(player_id)
        standings.append(
            {
                "player_id": player_id,
                "player_name": player.name if player else f"#{player_id}",
                "avatar_flag": player.avatar_flag if player else "🏴",
                "total_points": total_points or 0,
                "rank": rank,
                "hoy_points": hoy_rows.get(player_id, 0) or 0,
                "yesterday_rank": yesterday_ranks.get(player_id, None),
            }
        )
        prev_points = total_points

    return standings


def _delta_arrow(current_rank: int, yesterday_rank: int | None) -> str:
    """Return arrow string: ↑N, ↓N, or '—' if no snapshot."""
    if yesterday_rank is None:
        return "—"
    diff = yesterday_rank - current_rank
    if diff > 0:
        return f"↑{diff}"
    if diff < 0:
        return f"↓{abs(diff)}"
    return "—"


def standings_page() -> None:
    """Render the standings table inside the caller's current UI context.

    Call from within a tab_panel or page. Use refresh_standings() to
    re-render the content on a timer.
    """
    container = ui.column().classes("w-full")

    def refresh_standings():
        container.clear()
        with container:
            standings = _compute_standings()

            if not standings:
                ui.label("⏳ Aún no hay puntuaciones registradas.").classes(
                    "text-gray-400 text-center w-full mt-8"
                )
                ui.label(
                    "Las puntuaciones aparecerán cuando se jueguen partidos."
                ).classes("text-gray-400 text-sm text-center w-full")
                return

            # ── Table (mobile-first: dense, short headers) ──
            columns = [
                {"name": "pos", "label": "#", "field": "pos", "align": "center"},
                {"name": "name", "label": "Jugador", "field": "name", "align": "left"},
                {"name": "total", "label": "Pts", "field": "total", "align": "center"},
                {"name": "hoy", "label": "+Hoy", "field": "hoy", "align": "center"},
                {"name": "delta", "label": "Δ", "field": "delta", "align": "center"},
            ]

            rows_data = []
            for s in standings:
                rows_data.append(
                    {
                        "pos": s["rank"],
                        # Bandera + nombre juntos en una sola columna (ahorra ancho)
                        "name": f"{s['avatar_flag']}  {s['player_name']}",
                        "total": s["total_points"],
                        "hoy": (
                            f"+{s['hoy_points']}"
                            if s["hoy_points"] > 0
                            else str(s["hoy_points"])
                        ),
                        "delta": _delta_arrow(s["rank"], s["yesterday_rank"]),
                    }
                )

            ui.table(
                columns=columns,
                rows=rows_data,
                row_key="name",
            ).props("dense flat").classes("w-full standings-table")

    refresh_standings()

    # Auto-refresh every 45 seconds
    ui.timer(45, refresh_standings)
