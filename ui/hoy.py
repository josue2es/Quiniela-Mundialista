"""Tab 1 'Hoy' — today's matches with predictions, lock-on-kickoff, finished view.

§9: Partidos de hoy (match_date_local == hoy_ES). Layout mobile-first: cada
partido en una ui.card con una fila por equipo (bandera + nombre + input de
goles). Botón Guardar/Editar. Edición bloqueada si kickoff_utc <= now.
Tras finished: marcador real vs predicción + puntos.
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


def _stage_badge(stage: str | None) -> tuple[str, str]:
    """Return (label, css_class) for the stage chip."""
    s = (stage or "group").lower()
    if "group" in s or s == "grupos":
        return "Grupos", "stage-group"
    return "Eliminatoria", "stage-knockout"


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
    # kickoff_utc puede ser naive (sin tzinfo): forzar UTC antes de convertir,
    # igual que _can_edit, si no .astimezone() asume hora local del sistema.
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt_es = dt.astimezone(TZ_ES)
    return dt_es.strftime("%H:%M")


def _can_edit(match: dict) -> bool:
    """True if kickoff_utc is in the future and match not finished/cancelled."""
    kt = match.get("kickoff_utc")
    if not kt:
        # No kickoff time = assume editable (TBD matches)
        return True
    kickoff = datetime.fromisoformat(kt)
    if kickoff.tzinfo is None:
        kickoff = kickoff.replace(tzinfo=timezone.utc)
    now = _now_utc()
    status = match.get("status", "scheduled")
    return kickoff > now and status not in ("finished", "cancelled")


def _is_finished(match: dict) -> bool:
    return match.get("status") == "finished"


def _flag_el(flag: str | None) -> None:
    """Render a flag: image if it's a logo URL, else emoji/text label.

    Real API matches store a .png URL in home_flag/away_flag; demo/TBD use an
    emoji. URLs must render as <img>, not raw text.
    """
    if flag and isinstance(flag, str) and flag.startswith("http"):
        ui.image(flag).classes("flag-img")
    else:
        ui.label(flag or "🏳️").classes("flag-display")


def _team_label(flag: str | None, name: str) -> None:
    """Left side of a team row: flag + country name (truncates on overflow)."""
    with ui.row().classes("items-center gap-2 min-w-0 flex-1 flex-nowrap"):
        _flag_el(flag)
        ui.label(name).classes("team-name")


def hoy_page() -> None:
    """Render today's matches with predictions, lock-on-kickoff, finished view."""
    container = ui.column().classes("w-full gap-0")
    player_id = app.storage.user.get("player_id")

    def refresh():
        container.clear()
        with container:
            matches = _get_today_matches()

            if not matches:
                ui.label("🎉 ¡No hay partidos hoy!").classes(
                    "text-dim text-center w-full mt-8"
                )
                return

            ui.label("Partidos de hoy").classes(
                "text-lg font-bold w-full mb-2 px-1"
            )

            for m in matches:
                home = m.get("home")
                away = m.get("away")
                home_flag = m.get("home_flag") or "🏳️"
                away_flag = m.get("away_flag") or "🏳️"
                can_edit = _can_edit(m)
                finished = _is_finished(m)
                k_str = _kickoff_str(m)
                match_id = m["id"]
                is_tbd = home is None or away is None
                badge_text, badge_cls = _stage_badge(m.get("stage"))

                existing = None
                points = None
                if player_id:
                    existing = _get_existing_prediction(player_id, match_id)
                    if finished:
                        points = _get_match_score(player_id, match_id)

                with ui.card().classes("w-full mb-2 p-3 match-card"):
                    # ── Top row: stage badge + kickoff ──
                    with ui.row().classes("w-full items-center justify-between"):
                        ui.label(badge_text).classes(f"stage-badge {badge_cls}")
                        if k_str:
                            ui.label(f"🕑 {k_str}").classes("match-time")

                    # ── TBD: equipos por confirmar ──
                    if is_tbd:
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

                    # ── Finished: real score per team + prediction + points ──
                    if finished:
                        gh = m.get("goals_home")
                        ga = m.get("goals_away")
                        with ui.row().classes(
                            "w-full items-center justify-between gap-2 mt-2 flex-nowrap"
                        ):
                            _team_label(home_flag, home)
                            ui.label("?" if gh is None else str(gh)).classes(
                                "score-final"
                            )
                        with ui.row().classes(
                            "w-full items-center justify-between gap-2 mt-1 flex-nowrap"
                        ):
                            _team_label(away_flag, away)
                            ui.label("?" if ga is None else str(ga)).classes(
                                "score-final"
                            )
                        with ui.row().classes(
                            "w-full items-center justify-between mt-2"
                        ):
                            if existing:
                                ui.label(
                                    f"Tu pronóstico: {existing['pred_home']}–"
                                    f"{existing['pred_away']}"
                                ).classes("text-xs text-dim")
                            else:
                                ui.label("Sin pronóstico").classes(
                                    "text-xs text-dim"
                                )
                            pts = points if points is not None else "—"
                            ui.label(f"🏆 {pts} pts").classes("points-badge")
                        continue

                    # ── Editable / locked: one input per team ──
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

                    if not can_edit:
                        home_input.disable()
                        away_input.disable()
                        ui.label("🔒 Partido iniciado").classes(
                            "text-xs text-amber-500 mt-2"
                        )
                        continue

                    # ── Save row ──
                    with ui.row().classes(
                        "w-full items-center justify-between mt-2"
                    ):
                        feedback = ui.label("").classes("text-xs")

                        def make_save(
                            mid=match_id,
                            gh_in=home_input,
                            ga_in=away_input,
                            lbl=feedback,
                        ):
                            def save():
                                val_h = int(gh_in.value or 0)
                                val_a = int(ga_in.value or 0)
                                if not (0 <= val_h <= 100 and 0 <= val_a <= 100):
                                    lbl.classes(
                                        remove="text-green-500", add="text-red-500"
                                    )
                                    lbl.set_text("⚠️ Valores 0–100")
                                    return
                                ok = _save_prediction(player_id, mid, val_h, val_a)
                                if ok:
                                    lbl.classes(
                                        remove="text-red-500", add="text-green-500"
                                    )
                                    lbl.set_text("✅ Guardado")
                                else:
                                    lbl.classes(
                                        remove="text-green-500", add="text-red-500"
                                    )
                                    lbl.set_text("❌ Error")

                            return save

                        ui.button(
                            "Editar" if existing else "Guardar",
                            icon="edit" if existing else "save",
                            on_click=make_save(),
                        ).props("unelevated dense").classes("btn-save")

    refresh()
    ui.timer(60, refresh)
