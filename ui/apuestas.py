"""Tab 'Apuestas' — vista pública (solo lectura) de apuestas de partidos cerrados.

Visible para TODOS los jugadores logueados. Para cada Match FINISHED (más
reciente primero) muestra el marcador real y la predicción + puntos de los 11
jugadores, ordenados por puntos desc. NO muestra partidos abiertos (no revela
apuestas de partidos aún en juego).

Patrón de sesión: todo se copia a dicts dentro del `with SessionLocal()` para
evitar DetachedInstanceError (ver nota en data/models.py).
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from nicegui import ui

from data.database import SessionLocal
from data.models import Match, MatchScore, MatchStatus, Player, Prediction

TZ_ES = ZoneInfo("America/El_Salvador")


def _get_closed_bets() -> list[dict]:
    """Return finished matches (recent first), each with its 11 player rows.

    Each match dict: home, away, goals_home, goals_away, date_str, rows[].
    Each row: name, avatar_flag, pred ('x-y' or None), points.
    All built inside the session → safe to use after close.
    """
    with SessionLocal() as session:
        matches = (
            session.query(Match)
            .filter(Match.status == MatchStatus.FINISHED)
            .order_by(Match.kickoff_utc.desc())
            .all()
        )
        if not matches:
            return []

        players = session.query(Player).all()
        preds = {
            (p.player_id, p.match_id): (p.pred_home, p.pred_away)
            for p in session.query(Prediction).all()
        }
        scores = {
            (s.player_id, s.match_id): s.points
            for s in session.query(MatchScore).all()
        }

        result: list[dict] = []
        for m in matches:
            rows = []
            for p in players:
                pred = preds.get((p.id, m.id))
                rows.append(
                    {
                        "name": p.name,
                        "avatar_flag": p.avatar_flag,
                        "pred": f"{pred[0]}-{pred[1]}" if pred else None,
                        "points": scores.get((p.id, m.id), 0),
                    }
                )
            # Orden por puntos desc, luego nombre
            rows.sort(key=lambda r: (-r["points"], r["name"]))

            date_str = ""
            if m.kickoff_utc:
                kt = m.kickoff_utc
                if kt.tzinfo is None:
                    from datetime import timezone
                    kt = kt.replace(tzinfo=timezone.utc)
                date_str = kt.astimezone(TZ_ES).strftime("%d/%m %H:%M")

            result.append(
                {
                    "home": m.home or "TBD",
                    "away": m.away or "TBD",
                    "home_flag": m.home_flag,
                    "away_flag": m.away_flag,
                    "goals_home": m.goals_home,
                    "goals_away": m.goals_away,
                    "date_str": date_str,
                    "stage": m.stage,
                    "rows": rows,
                }
            )
        return result


def _flag_el(flag: str | None) -> None:
    if flag and isinstance(flag, str) and flag.startswith("http"):
        ui.image(flag).classes("flag-img")
    else:
        ui.label(flag or "🏳️").classes("flag-display")


def apuestas_page() -> None:
    """Render the read-only closed-bets view."""
    container = ui.column().classes("w-full gap-0")

    def refresh():
        container.clear()
        with container:
            matches = _get_closed_bets()
            if not matches:
                ui.label("⏳ Aún no hay partidos cerrados.").classes(
                    "text-dim text-center w-full mt-8"
                )
                return

            ui.label("Apuestas de partidos cerrados").classes(
                "text-lg font-bold w-full mb-2 px-1"
            )

            for m in matches:
                gh = m["goals_home"] if m["goals_home"] is not None else "?"
                ga = m["goals_away"] if m["goals_away"] is not None else "?"
                with ui.card().classes("w-full mb-3 p-3 match-card"):
                    # ── Línea 1: equipos (nombres completos) ──
                    with ui.row().classes("w-full items-center gap-2 flex-nowrap"):
                        _flag_el(m["home_flag"])
                        ui.label(m["home"]).classes("team-name flex-1")
                        ui.label(f"{gh}-{ga}").classes("score-final")
                        ui.label(m["away"]).classes("team-name flex-1 text-right")
                        _flag_el(m["away_flag"])
                    # ── Línea 2: fecha ──
                    if m["date_str"]:
                        with ui.row().classes("w-full justify-end mt-1"):
                            ui.label(m["date_str"]).classes("match-time")

                    # ── Tabla de jugadores ──
                    columns = [
                        {"name": "name", "label": "Jugador", "field": "name", "align": "left"},
                        {"name": "pred", "label": "Apuesta", "field": "pred", "align": "center"},
                        {"name": "pts", "label": "Pts", "field": "pts", "align": "center"},
                    ]
                    rows = [
                        {
                            "name": f"{r['avatar_flag']}  {r['name']}",
                            "pred": r["pred"] if r["pred"] else "—",
                            "pts": r["points"],
                        }
                        for r in m["rows"]
                    ]
                    ui.table(columns=columns, rows=rows, row_key="name").props(
                        "dense flat"
                    ).classes("w-full standings-table mt-2")

    refresh()
    ui.timer(60, refresh)
