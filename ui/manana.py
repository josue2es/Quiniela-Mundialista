"""Tab 3 'Mañana' — tomorrow's matches with TBD handling.

§9: Partidos de mañana (match_date_local == mañana_ES). Layout mobile-first:
una fila por equipo (bandera + nombre + input). Si home/away es null: mostrar
"Por confirmar" y deshabilitar inputs. Cuando sync_fixtures resuelve los equipos,
se habilita automáticamente.
"""

from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from nicegui import app, ui
from sqlalchemy import and_

from data.database import SessionLocal
from data.models import Match, Prediction
from ui import safe_timer

TZ_ES = ZoneInfo("America/El_Salvador")


def _today_es() -> date:
    return datetime.now(TZ_ES).date()


def _tomorrow_es() -> date:
    return _today_es() + timedelta(days=1)


def _stage_badge(stage: str | None) -> tuple[str, str]:
    s = (stage or "group").lower()
    if "group" in s or s == "grupos":
        return "Grupos", "stage-group"
    return "Eliminatoria", "stage-knockout"


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


def _kickoff_str(match: dict) -> str:
    kt = match.get("kickoff_utc")
    if not kt:
        return ""
    dt = datetime.fromisoformat(kt)
    # kickoff_utc puede ser naive: forzar UTC antes de convertir a ES.
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(TZ_ES).strftime("%H:%M")


def _flag_el(flag: str | None) -> None:
    """Render a flag: image if it's a logo URL, else emoji/text label.

    Real API matches store a .png URL in home_flag/away_flag; demo/TBD use an
    emoji. URLs must render as <img>, not raw text.
    """
    if flag and isinstance(flag, str) and flag.startswith("http"):
        ui.image(flag).classes("flag-img")
    else:
        ui.label(flag or "🏳️").classes("flag-display")


def _team_label(flag: str | None, name: str, dim: bool = False) -> None:
    with ui.row().classes("items-center gap-2 min-w-0 flex-1 flex-nowrap"):
        _flag_el(flag)
        ui.label(name).classes("team-name" + (" text-dim" if dim else ""))


def manana_page() -> None:
    """Render tomorrow's matches with TBD handling."""
    container = ui.column().classes("w-full gap-0")
    player_id = app.storage.user.get("player_id")

    def refresh():
        container.clear()
        with container:
            matches = _get_tomorrow_matches()

            if not matches:
                ui.label("🎉 ¡No hay partidos mañana!").classes(
                    "text-dim text-center w-full mt-8"
                )
                return

            ui.label("Partidos de mañana").classes(
                "text-lg font-bold w-full mb-2 px-1"
            )

            for m in matches:
                home = m["home"]
                away = m["away"]
                home_flag = m["home_flag"] or "🏳️"
                away_flag = m["away_flag"] or "🏳️"
                tbd = home is None or away is None
                k_str = _kickoff_str(m)
                badge_text, badge_cls = _stage_badge(m.get("stage"))

                existing = None
                if player_id and not tbd:
                    existing = _get_existing_prediction(player_id, m["id"])

                with ui.card().classes("w-full mb-2 p-3 match-card"):
                    # ── Top row: badge + kickoff ──
                    with ui.row().classes("w-full items-center justify-between"):
                        ui.label(badge_text).classes(f"stage-badge {badge_cls}")
                        if k_str:
                            ui.label(f"🕑 {k_str}").classes("match-time")

                    if tbd:
                        for fl in (home_flag, away_flag):
                            with ui.row().classes(
                                "w-full items-center gap-2 mt-2 flex-nowrap"
                            ):
                                _flag_el(fl)
                                ui.label("Por confirmar").classes(
                                    "team-name text-dim"
                                )
                        ui.label("🔒 Equipos por confirmar").classes(
                            "text-xs text-amber-500 mt-2"
                        )
                        continue

                    # ── Home row ──
                    with ui.row().classes(
                        "w-full items-center justify-between gap-2 mt-2 flex-nowrap"
                    ):
                        _team_label(home_flag, home)
                        home_input = (
                            ui.number(
                                value=existing["pred_home"] if existing else 0,
                                min=0,
                                max=100,
                            )
                            .props("outlined dense")
                            .classes("score-input")
                        )
                    # ── Away row ──
                    with ui.row().classes(
                        "w-full items-center justify-between gap-2 mt-1 flex-nowrap"
                    ):
                        _team_label(away_flag, away)
                        away_input = (
                            ui.number(
                                value=existing["pred_away"] if existing else 0,
                                min=0,
                                max=100,
                            )
                            .props("outlined dense")
                            .classes("score-input")
                        )

                    # ── Save row ──
                    with ui.row().classes(
                        "w-full items-center justify-between mt-2"
                    ):
                        feedback = ui.label("").classes("text-xs text-green-500")

                        def make_save(
                            mid=m["id"],
                            gh_in=home_input,
                            ga_in=away_input,
                            lbl=feedback,
                        ):
                            def save():
                                _save_prediction(
                                    player_id,
                                    mid,
                                    int(gh_in.value or 0),
                                    int(ga_in.value or 0),
                                )
                                lbl.set_text("✅ Guardado")

                            return save

                        ui.button(
                            "Editar" if existing else "Guardar",
                            icon="edit" if existing else "save",
                            on_click=make_save(),
                        ).props("unelevated dense").classes("btn-save")

    refresh()
    safe_timer(45, refresh)
