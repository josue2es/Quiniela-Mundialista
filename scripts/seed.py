#!/usr/bin/env python3
"""Seed de demostración — Dieciseisavos de final (Mundial 2026).

Genera datos de muestra para ver la app funcionando con la ronda de
dieciseisavos (round of 32). Las fechas se calculan RELATIVAS a "hoy" en
El Salvador (UTC-6), así que el seed siempre puebla correctamente las
pestañas "Hoy" y "Mañana" sin importar el día en que se ejecute.

Crea:
  - Los 11 jugadores del grupo (con avatar y password de 4 dígitos).
  - Partidos de HOY: 2 finalizados (con marcador), 1 en juego (bloqueado),
    1 programado más tarde (editable).
  - Partidos de MAÑANA: 4 dieciseisavos con equipos definidos (editables)
    + 1 placeholder TBD (octavos, equipos por confirmar → inputs bloqueados).
  - Predicciones de varios jugadores.
  - match_scores de los partidos finalizados (calculados con scoring.score()
    para los 11 jugadores; quien no predijo recibe 1 punto).
  - Snapshot de "ayer" para que la columna Δ de la tabla muestre flechas.

Uso:
    uv run python scripts/seed.py          # reset + seed de demostración
    uv run python scripts/seed.py --verify # cuenta filas por tabla
"""

import os
import sys
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data.database import init_db, session_scope, SessionLocal  # noqa: E402
from data.models import (  # noqa: E402
    Match,
    MatchScore,
    MatchStatus,
    Player,
    Prediction,
    StandingsSnapshot,
)
from scoring.quiniela import score  # noqa: E402

ES = ZoneInfo("America/El_Salvador")
UTC = timezone.utc


# ── Helpers de tiempo ─────────────────────────────────────────────────────────

def es_today():
    return datetime.now(ES).date()


def at_es(day, hour, minute=0):
    """Devuelve un datetime UTC-aware para una hora local ES en un día dado."""
    return datetime.combine(day, time(hour, minute), tzinfo=ES).astimezone(UTC)


# ── Jugadores (los 11 del grupo) ──────────────────────────────────────────────

PLAYERS = [
    {"name": "Cuestas",  "password": "1234", "avatar_flag": "🇦🇷"},
    {"name": "Vega",     "password": "2345", "avatar_flag": "🇧🇷"},
    {"name": "Chepe",    "password": "3456", "avatar_flag": "🇸🇻"},
    {"name": "Mamer",    "password": "4567", "avatar_flag": "🇲🇽"},
    {"name": "Josue",    "password": "5678", "avatar_flag": "🇪🇸"},
    {"name": "Tony",     "password": "6789", "avatar_flag": "🇫🇷"},
    {"name": "Frank",    "password": "7890", "avatar_flag": "🇩🇪"},
    {"name": "Colocha",  "password": "8901", "avatar_flag": "🇵🇹"},
    {"name": "Mumuja",   "password": "9012", "avatar_flag": "🇺🇾"},
    {"name": "Jaime",    "password": "0123", "avatar_flag": "🇮🇹"},
    {"name": "Chicapan", "password": "1357", "avatar_flag": "🇨🇴"},
]


def _build_matches(today, tomorrow):
    """Construye los partidos de demostración (hoy + mañana)."""
    now = datetime.now(UTC)

    return [
        # ── HOY: finalizados (alimentan la tabla y la columna +Hoy) ──
        {
            "external_id": "demo-r32-01",
            "home": "Argentina", "home_flag": "🇦🇷",
            "away": "México", "away_flag": "🇲🇽",
            "kickoff_utc": now - timedelta(hours=4),
            "match_date_local": today,
            "stage": "knockout", "status": MatchStatus.FINISHED,
            "goals_home": 2, "goals_away": 1,
        },
        {
            "external_id": "demo-r32-02",
            "home": "Francia", "home_flag": "🇫🇷",
            "away": "Brasil", "away_flag": "🇧🇷",
            "kickoff_utc": now - timedelta(hours=2),
            "match_date_local": today,
            "stage": "knockout", "status": MatchStatus.FINISHED,
            "goals_home": 0, "goals_away": 0,  # empate (se definiría por penales)
        },
        # ── HOY: en juego → edición bloqueada ──
        {
            "external_id": "demo-r32-03",
            "home": "Inglaterra", "home_flag": "🏴",
            "away": "Países Bajos", "away_flag": "🇳🇱",
            "kickoff_utc": now - timedelta(minutes=35),
            "match_date_local": today,
            "stage": "knockout", "status": MatchStatus.LIVE,
        },
        # ── HOY: programado más tarde → editable ──
        {
            "external_id": "demo-r32-04",
            "home": "España", "home_flag": "🇪🇸",
            "away": "Alemania", "away_flag": "🇩🇪",
            "kickoff_utc": now + timedelta(hours=3),
            "match_date_local": today,
            "stage": "knockout", "status": MatchStatus.SCHEDULED,
        },
        # ── MAÑANA: dieciseisavos con equipos definidos → editables ──
        {
            "external_id": "demo-r32-05",
            "home": "Portugal", "home_flag": "🇵🇹",
            "away": "Uruguay", "away_flag": "🇺🇾",
            "kickoff_utc": at_es(tomorrow, 10),
            "match_date_local": tomorrow,
            "stage": "knockout", "status": MatchStatus.SCHEDULED,
        },
        {
            "external_id": "demo-r32-06",
            "home": "Croacia", "home_flag": "🇭🇷",
            "away": "Bélgica", "away_flag": "🇧🇪",
            "kickoff_utc": at_es(tomorrow, 13),
            "match_date_local": tomorrow,
            "stage": "knockout", "status": MatchStatus.SCHEDULED,
        },
        {
            "external_id": "demo-r32-07",
            "home": "Colombia", "home_flag": "🇨🇴",
            "away": "Japón", "away_flag": "🇯🇵",
            "kickoff_utc": at_es(tomorrow, 16),
            "match_date_local": tomorrow,
            "stage": "knockout", "status": MatchStatus.SCHEDULED,
        },
        {
            "external_id": "demo-r32-08",
            "home": "Marruecos", "home_flag": "🇲🇦",
            "away": "Estados Unidos", "away_flag": "🇺🇸",
            "kickoff_utc": at_es(tomorrow, 19),
            "match_date_local": tomorrow,
            "stage": "knockout", "status": MatchStatus.SCHEDULED,
        },
        # ── MAÑANA: octavos placeholder → TBD, inputs bloqueados ──
        {
            "external_id": "demo-r16-01",
            "home": None, "home_flag": None,
            "away": None, "away_flag": None,
            "kickoff_utc": at_es(tomorrow, 21),
            "match_date_local": tomorrow,
            "stage": "knockout", "status": MatchStatus.SCHEDULED,
        },
    ]


# Predicciones de partidos FINALIZADOS, por nombre de jugador.
# (external_id → (pred_home, pred_away))
FINISHED_PREDICTIONS = {
    "Cuestas":  {"demo-r32-01": (2, 1), "demo-r32-02": (0, 0)},  # 3 + 3 = 6
    "Vega":     {"demo-r32-01": (1, 0), "demo-r32-02": (1, 1)},  # 2 + 2 = 4
    "Chepe":    {"demo-r32-01": (0, 2), "demo-r32-02": (2, 1)},  # 1 + 1 = 2
    "Mamer":    {"demo-r32-01": (3, 1), "demo-r32-02": (0, 0)},  # 2 + 3 = 5
    "Josue":    {"demo-r32-01": (2, 1), "demo-r32-02": (1, 0)},  # 3 + 1 = 4
    "Tony":     {"demo-r32-01": (1, 1), "demo-r32-02": (2, 2)},  # 1 + 2 = 3
    "Colocha":  {"demo-r32-01": (2, 0)},                          # 2 (+1 sin pred)
    "Jaime":    {"demo-r32-01": (2, 1)},                          # 3 (+1 sin pred)
    # Frank, Mumuja, Chicapan: sin predicciones → 1 punto por partido
}

# Predicciones de partidos PROGRAMADOS (para mostrar botón "Editar" vs "Guardar").
SCHEDULED_PREDICTIONS = {
    "Cuestas": {"demo-r32-05": (2, 1), "demo-r32-04": (1, 1)},
    "Josue":   {"demo-r32-06": (1, 1)},
    "Vega":    {"demo-r32-05": (0, 0)},
}


def seed():
    """Inserta todos los datos de demostración (reset previo)."""
    print("⚠️  Reiniciando la base de datos (drop + create) para el seed de demo...")
    init_db(drop_all=True)

    today = es_today()
    tomorrow = today + timedelta(days=1)
    yesterday = today - timedelta(days=1)

    with session_scope() as session:
        # ── Jugadores ──
        players = {}
        for p in PLAYERS:
            player = Player(
                name=p["name"],
                password=p["password"],
                avatar_flag=p["avatar_flag"],
                is_setup=True,  # demo: ya configurados, listos para login
            )
            session.add(player)
            players[p["name"]] = player
        session.flush()
        print(f"✅ {len(players)} jugadores insertados")

        # ── Partidos ──
        matches = {}
        for m in _build_matches(today, tomorrow):
            match = Match(**m)
            session.add(match)
            matches[m["external_id"]] = match
        session.flush()
        print(f"✅ {len(matches)} partidos insertados (hoy + mañana)")

        # ── Predicciones ──
        pred_count = 0
        for source in (FINISHED_PREDICTIONS, SCHEDULED_PREDICTIONS):
            for name, preds in source.items():
                for ext_id, (ph, pa) in preds.items():
                    session.add(
                        Prediction(
                            player_id=players[name].id,
                            match_id=matches[ext_id].id,
                            pred_home=ph,
                            pred_away=pa,
                        )
                    )
                    pred_count += 1
        print(f"✅ {pred_count} predicciones insertadas")

        # ── match_scores de los partidos finalizados (los 11 jugadores) ──
        score_count = 0
        finished = [m for m in matches.values() if m.status == MatchStatus.FINISHED]
        for match in finished:
            for name, player in players.items():
                preds = FINISHED_PREDICTIONS.get(name, {})
                if match.external_id in preds:
                    ph, pa = preds[match.external_id]
                    pts = score(ph, pa, match.goals_home, match.goals_away)
                else:
                    pts = 1  # sin predicción → 1 punto
                session.add(
                    MatchScore(
                        player_id=player.id,
                        match_id=match.id,
                        points=pts,
                    )
                )
                score_count += 1
        print(f"✅ {score_count} match_scores calculados ({len(finished)} partidos finalizados)")

        # ── Standings de "ayer" (para que la columna Δ muestre movimiento) ──
        # Totales actuales (suma de match_scores) → orden → rank de competencia.
        session.flush()
        from sqlalchemy import func

        totals = (
            session.query(
                MatchScore.player_id, func.sum(MatchScore.points)
            )
            .group_by(MatchScore.player_id)
            .order_by(func.sum(MatchScore.points).desc())
            .all()
        )
        order = [pid for pid, _ in totals]
        n = len(order)
        # Rotamos el orden de ayer para garantizar flechas ↑/↓ variadas.
        snap_count = 0
        for i, pid in enumerate(order):
            total = dict(totals)[pid] or 0
            yesterday_rank = ((i + 2) % n) + 1  # posición rotada
            session.add(
                StandingsSnapshot(
                    player_id=pid,
                    snapshot_date_local=yesterday,
                    total_points=total,
                    rank=yesterday_rank,
                )
            )
            snap_count += 1
        print(f"✅ {snap_count} snapshots de ayer insertados")

    print("\n🎉 Seed de demostración listo.")
    print(f"   Hoy ES: {today}  |  Mañana ES: {tomorrow}")
    print("   Credenciales de ejemplo:")
    print("     Cuestas / 1234   ·   Josue / 5678   ·   Vega / 2345")
    print("   Levantá la app con:  uv run python main.py")


def verify():
    from sqlalchemy import text

    with SessionLocal() as session:
        tables = [
            "players",
            "matches",
            "predictions",
            "match_scores",
            "standings_snapshots",
        ]
        for t in tables:
            count = session.execute(text(f"SELECT COUNT(*) FROM {t}")).scalar()
            print(f"  {t}: {count} filas")


if __name__ == "__main__":
    if "--verify" in sys.argv:
        verify()
    else:
        seed()
