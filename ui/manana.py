"""Tab 3 'Mañana' — tomorrow's matches with TBD handling.

§9: Partidos de mañana (match_date_local == mañana_ES). Si home/away es null:
mostrar "TBD" y deshabilitar inputs de predicción. Cuando sync_fixtures resuelve
los equipos (tras finalizar último partido del día), habilitar automáticamente.
"""

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from nicegui import app, ui
from sqlalchemy import and_

from data.database import SessionLocal
from data.models import Match, Prediction

TZ_ES = ZoneInfo("America/El_Salvador")


def _today_es() -> date:
    return datetime.now(TZ_ES).date()


def _tomorrow_es() -> date:
    return _today_es() + timedelta(days=1)


def _get_tomorrow_matches() -> list[dict]:
    """Return tomorrow's matches as flat dicts for the UI."""
    tomorrow = _today_es() + timedelta(days=1)

    with SessionLocal() as session:
        matches = (
            session.query(Match)
            .filter(Match.match_date_local == tomorrow)
            .order_by(Match.kickoff_utc)
            .all()
        )
        return [m.to_dict() for m in matches]


def _get_existing_prediction(player_id: int, match_id: int) -> dict | None:
    """Return existing prediction as dict, or None."""
    with SessionLocal() as session:
        pred = (
            session.query(Prediction)
            .filter(
                and_(
                    Prediction.player_id == player_id,
                    Prediction.match_id == match_id,
                )
            )
            .first()
        )
        if pred:
            return {"pred_home": pred.pred_home, "pred_away": pred.pred_away}
    return None


def _save_prediction(
    player_id: int, match_id: int, pred_home: int, pred_away: int
) -> None:
    """Upsert a prediction (idempotent — overwrites existing)."""
    # Validate range 0-100 per §4 and §9
    pred_home = max(0, min(100, pred_home))
    pred_away = max(0, min(100, pred_away))
    with SessionLocal() as session:
        pred = (
            session.query(Prediction)
            .filter(
                and_(
                    Prediction.player_id == player_id,
                    Prediction.match_id == match_id,
                )
            )
            .first()
        )
        if pred:
            pred.pred_home = pred_home
            pred.pred_away = pred_away
        else:
            session.add(
                Prediction(
                    player_id=player_id,
                    match_id=match_id,
                    pred_home=pred_home,
                    pred_away=pred_away,
                )
            )
        session.commit()


def manana_page() -> None:
    """Render tomorrow's matches with TBD handling."""
    container = ui.column().classes("w-full")
    player_id = app.storage.user.get("player_id")

    def is_tbd(match: dict) -> bool:
        return match["home"] is None or match["away"] is None

    def refresh():
        container.clear()
        with container:
            matches = _get_tomorrow_matches()

            if not matches:
                ui.label("🎉 ¡No hay partidos programados para mañana!").classes(
                    "text-gray-400 text-center w-full mt-8"
                )
                return

            ui.label("Partidos de mañana").classes(
                "text-xl font-bold w-full mb-4"
            )

            for m in matches:
                home = m["home"]
                away = m["away"]
                home_flag = m["home_flag"] or "🏳️"
                away_flag = m["away_flag"] or "🏳️"
                tbd = is_tbd(m)

                with ui.card().classes("w-full mb-3 p-4"):
                    with ui.row().classes("w-full items-center justify-between"):
                        # ── Teams display ──
                        with ui.row().classes("items-center gap-3"):
                            ui.label(home_flag).classes("text-2xl")
                            ui.label(
                                home if home else "TBD"
                            ).classes("text-lg font-semibold")
                            ui.label("vs").classes("text-gray-400 mx-2")
                            ui.label(
                                away if away else "TBD"
                            ).classes("text-lg font-semibold")
                            ui.label(away_flag).classes("text-2xl")

                        # ── Kickoff time ──
                        kickoff_str = ""
                        if m["kickoff_utc"]:
                            kt = datetime.fromisoformat(m["kickoff_utc"])
                            kt_es = kt.astimezone(TZ_ES)
                            kickoff_str = kt_es.strftime("%H:%M")
                        ui.label(kickoff_str).classes(
                            "text-sm text-gray-500"
                        )

                    # ── Prediction inputs ──
                    existing = None
                    if player_id:
                        existing = _get_existing_prediction(
                            player_id, m["id"]
                        )

                    with ui.row().classes(
                        "w-full items-center gap-3 mt-3"
                    ):
                        goals_home = (
                            ui.number(
                                label="Goles",
                                value=existing["pred_home"]
                                if existing and existing["pred_home"] is not None
                                else 0,
                                min=0,
                                max=100,
                            )
                            .props("outlined dense")
                            .classes("w-20")
                        )
                        goals_away = (
                            ui.number(
                                label="Goles",
                                value=existing["pred_away"]
                                if existing and existing["pred_away"] is not None
                                else 0,
                                min=0,
                                max=100,
                            )
                            .props("outlined dense")
                            .classes("w-20")
                        )

                        if tbd:
                            goals_home.disable()
                            goals_away.disable()
                            ui.label(
                                "🔒 Equipos por confirmar"
                            ).classes("text-sm text-amber-500")
                        else:
                            saved_label = ui.label("").classes(
                                "text-xs text-green-500"
                            )

                            def make_save(
                                mid=m["id"],
                                gh=goals_home,
                                ga=goals_away,
                                lbl=saved_label,
                            ):
                                def save():
                                    _save_prediction(
                                        player_id,
                                        mid,
                                        int(gh.value),
                                        int(ga.value),
                                    )
                                    lbl.set_text("✅ Guardado")

                                return save

                            ui.button(
                                "Guardar",
                                icon="save",
                                on_click=make_save(),
                            ).props("flat dense").classes("ml-2")

                    # ── Stage badge ──
                    with ui.row().classes("w-full justify-end mt-1"):
                        stage_label = m.get("stage", "group") or "group"
                        ui.label(stage_label.upper()).classes(
                            "text-xs text-gray-500 bg-gray-800 rounded px-2 py-0.5"
                        )

    refresh()

    # Auto-refresh every 45 seconds so TBD teams get resolved automatically
    ui.timer(45, refresh)
