"""Tab 1 'Hoy' — today's matches with predictions, lock-on-kickoff, finished view.

§9: Partidos de hoy (match_date_local == hoy_ES). Cada partido en ui.card:
bandera + país + ui.number(min=0, max=100). Botones Guardar/Editar.
Editar deshabilitado si kickoff_utc <= now. Tras finished: mostrar marcador
real vs predicción + puntos.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

from nicegui import app, ui
from sqlalchemy import and_

from data.database import SessionLocal
from data.models import Match, MatchScore, Prediction

TZ_ES = ZoneInfo("America/El_Salvador")


def _today_es() -> date:
    return datetime.now(TZ_ES).date()


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _get_today_matches() -> list[dict]:
    """Return today's matches as flat dicts ordered by kickoff_utc."""
    today = _today_es()

    with SessionLocal() as session:
        matches = (
            session.query(Match)
            .filter(Match.match_date_local == today)
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
            return {
                "id": pred.id,
                "pred_home": pred.pred_home,
                "pred_away": pred.pred_away,
            }
    return None


def _get_match_score(player_id: int, match_id: int) -> int | None:
    """Return points for this player+match, or None if not scored yet."""
    with SessionLocal() as session:
        ms = (
            session.query(MatchScore)
            .filter(
                and_(
                    MatchScore.player_id == player_id,
                    MatchScore.match_id == match_id,
                )
            )
            .first()
        )
        if ms:
            return ms.points
    return None


def _save_prediction(
    player_id: int, match_id: int, pred_home: int, pred_away: int
) -> bool:
    """Upsert a prediction (idempotent). Returns True on success.

    Validates 0-100 range before writing.
    """
    if not (0 <= pred_home <= 100 and 0 <= pred_away <= 100):
        return False

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
    return True


def _kickoff_str(match: dict) -> str:
    """Format kickoff time in ES timezone, or empty string."""
    kt = match.get("kickoff_utc")
    if not kt:
        return ""
    dt = datetime.fromisoformat(kt)
    dt_es = dt.astimezone(TZ_ES)
    return dt_es.strftime("%H:%M")


def _can_edit(match: dict) -> bool:
    """True if kickoff_utc is in the future and match not finished/cancelled."""
    kt = match.get("kickoff_utc")
    if not kt:
        # No kickoff time = assume editable (TBD matches)
        return True
    kickoff = datetime.fromisoformat(kt)
    # Ensure both are offset-aware for comparison
    if kickoff.tzinfo is None:
        kickoff = kickoff.replace(tzinfo=timezone.utc)
    now = _now_utc()
    status = match.get("status", "scheduled")
    return kickoff > now and status not in ("finished", "cancelled")


def _is_finished(match: dict) -> bool:
    return match.get("status") == "finished"


def hoy_page() -> None:
    """Render today's matches with predictions, lock-on-kickoff, finished view."""
    container = ui.column().classes("w-full")
    player_id = app.storage.user.get("player_id")

    def refresh():
        container.clear()
        with container:
            matches = _get_today_matches()

            if not matches:
                ui.label("🎉 ¡No hay partidos programados para hoy!").classes(
                    "text-gray-400 text-center w-full mt-8"
                )
                return

            ui.label("Partidos de hoy").classes("text-xl font-bold w-full mb-4")

            now = _now_utc()

            for m in matches:
                home = m.get("home")
                away = m.get("away")
                home_flag = m.get("home_flag") or "🏳️"
                away_flag = m.get("away_flag") or "🏳️"
                can_edit = _can_edit(m)
                finished = _is_finished(m)
                k_str = _kickoff_str(m)
                match_id = m["id"]

                # ── Fetch existing prediction & score ──
                existing = None
                points = None
                if player_id:
                    existing = _get_existing_prediction(player_id, match_id)
                    if finished:
                        points = _get_match_score(player_id, match_id)

                # ── Card ──
                with ui.card().classes("w-full mb-3 p-4 match-card"):
                    # ── Header row: teams + kickoff ──
                    with ui.row().classes("w-full items-center justify-between"):
                        with ui.row().classes("items-center gap-3"):
                            ui.label(home_flag).classes("flag-display")
                            ui.label(
                                home if home else "TBD"
                            ).classes("text-lg font-bold")
                            ui.label("vs").classes("vs-divider mx-1")
                            ui.label(
                                away if away else "TBD"
                            ).classes("text-lg font-bold")
                            ui.label(away_flag).classes("flag-display")
                        if k_str:
                            ui.label(k_str).classes("match-time")

                    # ── TBD handling ──
                    if home is None or away is None:
                        ui.label(
                            "🔒 Equipos por confirmar"
                        ).classes("text-sm text-amber-500 mt-2")
                        with ui.row().classes("w-full justify-end mt-1"):
                            stage = m.get("stage", "group") or "group"
                            badge_class = f"stage-badge stage-{stage}"
                            ui.label(stage.upper()).classes(badge_class)
                        continue

                    # ── Finished match: show real score vs prediction + points ──
                    if finished:
                        goals_h = m.get("goals_home")
                        goals_a = m.get("goals_away")

                        with ui.row().classes("w-full items-center gap-4 mt-3"):
                            # Real result
                            with ui.column().classes("items-center"):
                                ui.label("Real").classes(
                                    "text-xs text-gray-500"
                                )
                                real_str = (
                                    f"{goals_h} - {goals_a}"
                                    if goals_h is not None
                                    and goals_a is not None
                                    else "? - ?"
                                )
                                ui.label(real_str).classes(
                                    "text-xl font-bold"
                                )

                            # Prediction
                            with ui.column().classes("items-center"):
                                ui.label("Tu predicción").classes(
                                    "text-xs text-gray-500"
                                )
                                if existing:
                                    pred_str = (
                                        f"{existing['pred_home']} - "
                                        f"{existing['pred_away']}"
                                    )
                                else:
                                    pred_str = "—"
                                ui.label(pred_str).classes(
                                    "text-lg"
                                )

                            # Points
                            with ui.column().classes("items-center"):
                                ui.label("Puntos").classes(
                                    "text-xs text-gray-500"
                                )
                                pts_str = (
                                    str(points) if points is not None else "—"
                                )
                                ui.label(pts_str).classes(
                                    "text-lg font-bold text-amber-400"
                                )

                        # ── Stage badge ──
                        with ui.row().classes("w-full justify-end mt-2"):
                            stage = m.get("stage", "group") or "group"
                            badge_class = f"stage-badge stage-{stage}"
                            ui.label(stage.upper()).classes(badge_class)
                        continue

                    # ── Editable / locked state ──
                    with ui.row().classes("w-full items-center gap-3 mt-3"):
                        goals_home_input = (
                            ui.number(
                                label="Goles local",
                                value=(
                                    existing["pred_home"]
                                    if existing
                                    else 0
                                ),
                                min=0,
                                max=100,
                            )
                            .props("outlined dense")
                            .classes("w-24")
                        )
                        goals_away_input = (
                            ui.number(
                                label="Goles visitante",
                                value=(
                                    existing["pred_away"]
                                    if existing
                                    else 0
                                ),
                                min=0,
                                max=100,
                            )
                            .props("outlined dense")
                            .classes("w-24")
                        )

                        if not can_edit:
                            goals_home_input.disable()
                            goals_away_input.disable()
                            ui.label("🔒 Partido iniciado").classes(
                                "text-sm text-amber-500 ml-2"
                            )
                        else:
                            # ── Feedback label ──
                            saved_label = ui.label("").classes(
                                "text-xs text-green-500"
                            )

                            # ── Validation error label ──
                            error_label = ui.label("").classes(
                                "text-xs text-red-500"
                            )

                            def make_save(
                                mid=match_id,
                                gh=goals_home_input,
                                ga=goals_away_input,
                                lbl=saved_label,
                                err=error_label,
                            ):
                                def save():
                                    val_h = int(gh.value)
                                    val_a = int(ga.value)
                                    if not (0 <= val_h <= 100 and 0 <= val_a <= 100):
                                        err.set_text(
                                            "⚠️ Valores deben ser 0-100"
                                        )
                                        lbl.set_text("")
                                        return
                                    err.set_text("")
                                    ok = _save_prediction(
                                        player_id, mid, val_h, val_a
                                    )
                                    if ok:
                                        lbl.set_text("✅ Guardado")
                                    else:
                                        err.set_text("❌ Error al guardar")

                                return save

                            btn_label = (
                                "Editar" if existing else "Guardar"
                            )
                            btn_icon = "edit" if existing else "save"
                            ui.button(
                                btn_label,
                                icon=btn_icon,
                                on_click=make_save(),
                            ).props("flat dense").classes("ml-2")

                    # ── Stage badge ──
                    with ui.row().classes("w-full justify-end mt-1"):
                        stage = m.get("stage", "group") or "group"
                        ui.label(stage.upper()).classes(
                            "text-xs text-gray-500 bg-gray-800 rounded px-2 py-0.5"
                        )

    refresh()

    # Auto-refresh every 60 seconds
    ui.timer(60, refresh)
