"""Tab 'Admin' — corrección de predicciones de partidos cerrados (solo is_admin).

La tab solo se renderiza si el jugador logueado es admin (ver auth.is_admin).
Funcionalidad:
  - Elegir un partido FINISHED.
  - Ver los 11 jugadores con su predicción y puntos actuales.
  - Editar la predicción de cualquiera → re-scoring explícito (borra y recalcula
    el MatchScore) + registro en admin_audit_log.

Re-scoring: el _score_match de poll_results es idempotente (salta jugadores ya
puntuados), así que NO sirve para re-puntuar. Acá se borra y recalcula a mano.
No se tocan los totales: ui/standings.py los recalcula al vuelo.
"""

from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from typing import Callable

from nicegui import app, ui
from sqlalchemy import and_

from auth import is_admin
from data.database import SessionLocal
from data.models import (
    AdminAuditLog,
    Match,
    MatchScore,
    MatchStatus,
    Player,
    Prediction,
)
from scoring.quiniela import score as compute_score

TZ_ES = ZoneInfo("America/El_Salvador")


# ── Re-scoring service (explícito: borra y recalcula) ──────────────────────────


def apply_correction(
    admin_id: int,
    match_id: int,
    player_id: int,
    new_home: int,
    new_away: int,
    session_factory: Callable = SessionLocal,
) -> dict:
    """Upsert la predicción de un jugador en un partido cerrado y re-puntúa.

    Pasos (todo en una transacción):
      a. Valida rango 0-100 y que el partido esté FINISHED con goles.
      b. Verifica que admin_id sea admin.
      c. Upsert de Prediction (captura la vieja para auditoría).
      d. Borra el MatchScore previo de (player_id, match_id) (captura puntos viejos).
      e. Recalcula con scoring.score() e inserta el nuevo MatchScore.
      f. Inserta AdminAuditLog. Commit.

    Returns dict con old/new pred y old/new points. Lanza ValueError si algo falla.
    """
    if not (0 <= new_home <= 100 and 0 <= new_away <= 100):
        raise ValueError("Los goles deben estar entre 0 y 100.")

    with session_factory() as session:
        admin = session.get(Player, admin_id)
        if not admin or not admin.is_admin:
            raise ValueError("No autorizado: el usuario no es admin.")

        match = session.get(Match, match_id)
        if match is None or match.status != MatchStatus.FINISHED:
            raise ValueError("El partido no está cerrado.")
        if match.goals_home is None or match.goals_away is None:
            raise ValueError("El partido no tiene marcador registrado.")

        player = session.get(Player, player_id)
        if player is None:
            raise ValueError("Jugador inexistente.")

        # ── Predicción vieja (para auditoría) ──
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
        old_pred_home = pred.pred_home if pred else None
        old_pred_away = pred.pred_away if pred else None

        # ── Upsert de la predicción ──
        if pred:
            pred.pred_home = new_home
            pred.pred_away = new_away
        else:
            session.add(
                Prediction(
                    player_id=player_id,
                    match_id=match_id,
                    pred_home=new_home,
                    pred_away=new_away,
                )
            )

        # ── Borrar MatchScore previo (puntos viejos) ──
        old_score = (
            session.query(MatchScore)
            .filter(
                and_(
                    MatchScore.player_id == player_id,
                    MatchScore.match_id == match_id,
                )
            )
            .first()
        )
        old_points = old_score.points if old_score else None
        if old_score:
            session.delete(old_score)
            session.flush()  # asegurar el delete antes del insert (unique constraint)

        # ── Recalcular e insertar ──
        new_points = compute_score(
            new_home, new_away, match.goals_home, match.goals_away
        )
        session.add(
            MatchScore(player_id=player_id, match_id=match_id, points=new_points)
        )

        # ── Auditoría ──
        session.add(
            AdminAuditLog(
                admin_id=admin_id,
                match_id=match_id,
                player_id=player_id,
                old_pred_home=old_pred_home,
                old_pred_away=old_pred_away,
                new_pred_home=new_home,
                new_pred_away=new_away,
                old_points=old_points,
                new_points=new_points,
            )
        )

        session.commit()

        return {
            "old_pred": (old_pred_home, old_pred_away),
            "new_pred": (new_home, new_away),
            "old_points": old_points,
            "new_points": new_points,
        }


# ── Data loaders (a dicts, dentro de sesión) ───────────────────────────────────


def _finished_matches() -> list[dict]:
    with SessionLocal() as session:
        matches = (
            session.query(Match)
            .filter(Match.status == MatchStatus.FINISHED)
            .order_by(Match.kickoff_utc.desc())
            .all()
        )
        return [
            {
                "id": m.id,
                "label": f"{m.home or 'TBD'} {m.goals_home}-{m.goals_away} {m.away or 'TBD'}",
                "goals_home": m.goals_home,
                "goals_away": m.goals_away,
                "home": m.home,
                "away": m.away,
            }
            for m in matches
        ]


def _player_rows(match_id: int) -> list[dict]:
    with SessionLocal() as session:
        players = session.query(Player).order_by(Player.name).all()
        preds = {
            p.player_id: (p.pred_home, p.pred_away)
            for p in session.query(Prediction).filter_by(match_id=match_id).all()
        }
        scores = {
            s.player_id: s.points
            for s in session.query(MatchScore).filter_by(match_id=match_id).all()
        }
        rows = []
        for p in players:
            pred = preds.get(p.id)
            rows.append(
                {
                    "player_id": p.id,
                    "name": p.name,
                    "avatar_flag": p.avatar_flag,
                    "pred_home": pred[0] if pred else 0,
                    "pred_away": pred[1] if pred else 0,
                    "has_pred": pred is not None,
                    "points": scores.get(p.id),
                }
            )
        return rows


def _audit_rows(limit: int = 25) -> list[dict]:
    with SessionLocal() as session:
        logs = (
            session.query(AdminAuditLog)
            .order_by(AdminAuditLog.created_at.desc())
            .limit(limit)
            .all()
        )
        if not logs:
            return []
        pmap = {p.id: p.name for p in session.query(Player).all()}
        mmap = {
            m.id: f"{m.home or 'TBD'} vs {m.away or 'TBD'}"
            for m in session.query(Match).all()
        }
        out = []
        for log in logs:
            when = log.created_at
            if when and when.tzinfo is None:
                when = when.replace(tzinfo=timezone.utc)
            out.append(
                {
                    "when": when.astimezone(TZ_ES).strftime("%d/%m %H:%M") if when else "",
                    "admin": pmap.get(log.admin_id, f"#{log.admin_id}"),
                    "player": pmap.get(log.player_id, f"#{log.player_id}"),
                    "match": mmap.get(log.match_id, f"#{log.match_id}"),
                    "old_pred": (
                        f"{log.old_pred_home}-{log.old_pred_away}"
                        if log.old_pred_home is not None
                        else "—"
                    ),
                    "new_pred": f"{log.new_pred_home}-{log.new_pred_away}",
                    "old_points": log.old_points if log.old_points is not None else "—",
                    "new_points": log.new_points,
                }
            )
        return out


# ── UI ─────────────────────────────────────────────────────────────────────────


def admin_page() -> None:
    """Render the admin correction panel. Gated by is_admin()."""
    if not is_admin():
        ui.label("⛔ Acceso restringido a administradores.").classes(
            "text-red-500 text-center w-full mt-8"
        )
        return

    admin_id = app.storage.user.get("player_id")
    state: dict = {"match_id": None}

    ui.label("Panel de administración").classes("text-lg font-bold w-full mb-2 px-1")
    ui.label(
        "Corregí la predicción de un jugador en un partido cerrado. "
        "Al guardar se recalcula el puntaje y la tabla se reordena sola."
    ).classes("text-xs text-dim w-full mb-3 px-1")

    finished = _finished_matches()

    # ── Selector de partido (arriba) ──
    def on_match_change(e) -> None:
        state["match_id"] = e.value
        render_editor()

    if finished:
        state["match_id"] = finished[0]["id"]
        ui.select(
            options={m["id"]: m["label"] for m in finished},
            value=state["match_id"],
            label="Partido cerrado",
            on_change=on_match_change,
        ).props("outlined").classes("w-full mb-3")
    else:
        ui.label("No hay partidos cerrados para corregir.").classes(
            "text-dim text-center w-full mt-4"
        )

    editor = ui.column().classes("w-full")
    audit = ui.column().classes("w-full mt-4")

    def render_audit() -> None:
        audit.clear()
        with audit:
            rows = _audit_rows()
            ui.label("Historial de correcciones").classes(
                "text-base font-bold w-full mb-1 px-1"
            )
            if not rows:
                ui.label("Sin correcciones todavía.").classes("text-xs text-dim px-1")
                return
            columns = [
                {"name": "when", "label": "Fecha", "field": "when", "align": "left"},
                {"name": "admin", "label": "Admin", "field": "admin", "align": "left"},
                {"name": "match", "label": "Partido", "field": "match", "align": "left"},
                {"name": "player", "label": "Jugador", "field": "player", "align": "left"},
                {"name": "change", "label": "Apuesta", "field": "change", "align": "center"},
                {"name": "pts", "label": "Pts", "field": "pts", "align": "center"},
            ]
            data = [
                {
                    "when": r["when"],
                    "admin": r["admin"],
                    "match": r["match"],
                    "player": r["player"],
                    "change": f"{r['old_pred']} → {r['new_pred']}",
                    "pts": f"{r['old_points']} → {r['new_points']}",
                }
                for r in rows
            ]
            ui.table(columns=columns, rows=data, row_key="when").props(
                "dense flat"
            ).classes("w-full standings-table")

    def render_editor() -> None:
        editor.clear()
        with editor:
            if state["match_id"] is None:
                return
            rows = _player_rows(state["match_id"])
            for r in rows:
                with ui.card().classes("w-full mb-2 p-3"):
                    # Línea 1: jugador + puntos actuales
                    with ui.row().classes(
                        "w-full items-center justify-between flex-nowrap"
                    ):
                        with ui.row().classes(
                            "items-center gap-2 min-w-0 flex-1 flex-nowrap"
                        ):
                            ui.label(r["avatar_flag"]).classes("flag-display")
                            ui.label(r["name"]).classes("team-name")
                        pts = r["points"] if r["points"] is not None else "—"
                        ui.label(f"🏆 {pts}").classes("points-badge")
                    # Línea 2: editar predicción + guardar
                    with ui.row().classes(
                        "w-full items-center gap-2 mt-2 flex-nowrap"
                    ):
                        h_in = (
                            ui.number(value=r["pred_home"], min=0, max=100)
                            .props("outlined dense")
                            .classes("score-input")
                        )
                        ui.label("-").classes("text-dim")
                        a_in = (
                            ui.number(value=r["pred_away"], min=0, max=100)
                            .props("outlined dense")
                            .classes("score-input")
                        )
                        ui.space()

                        def make_save(pid=r["player_id"], gh=h_in, ga=a_in):
                            def save():
                                try:
                                    res = apply_correction(
                                        admin_id=admin_id,
                                        match_id=state["match_id"],
                                        player_id=pid,
                                        new_home=int(gh.value or 0),
                                        new_away=int(ga.value or 0),
                                    )
                                    ui.notify(
                                        f"✅ Guardado: {res['old_points']} → "
                                        f"{res['new_points']} pts",
                                        type="positive",
                                    )
                                    render_editor()
                                    render_audit()
                                except ValueError as e:
                                    ui.notify(f"❌ {e}", type="negative")

                            return save

                        ui.button(
                            "Guardar", icon="save", on_click=make_save()
                        ).props("unelevated dense").classes("btn-save")

    render_editor()
    render_audit()
