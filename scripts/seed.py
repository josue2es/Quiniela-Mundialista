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
    para los 11 jugadores; quien no predijo recibe 0 puntos).
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
    {"name": "Cuestas",  "password": "1234", "avatar_flag": "🇦🇷", "initial_points": 0},
    {"name": "Vega",     "password": "2345", "avatar_flag": "🇧🇷", "initial_points": 5},
    {"name": "Chepe",    "password": "3456", "avatar_flag": "🇸🇻", "initial_points": 10},
    {"name": "Mamer",    "password": "4567", "avatar_flag": "🇲🇽", "initial_points": 0},
    {"name": "Josue",    "password": "5678", "avatar_flag": "🇪🇸", "initial_points": 3},
    {"name": "Tony",     "password": "6789", "avatar_flag": "🇫🇷", "initial_points": 8},
    {"name": "Frank",    "password": "7890", "avatar_flag": "🇩🇪", "initial_points": 12},
    {"name": "Colocha",  "password": "8901", "avatar_flag": "🇵🇹", "initial_points": 0},
    {"name": "Mumuja",   "password": "9012", "avatar_flag": "🇺🇾", "initial_points": 6},
    {"name": "Jaime",    "password": "0123", "avatar_flag": "🇮🇹", "initial_points": 0},
    {"name": "Chicapan", "password": "1357", "avatar_flag": "🇨🇴", "initial_points": 15},
]


# Cierre de fase de grupos HOY (equipos eliminados) — alimentan la tabla.
# (ext_id, home, home_flag, away, away_flag)
GROUP_TODAY = [
    ("demo-grp-01", "Túnez", "🇹🇳", "Argelia", "🇩🇿"),     # finalizado 1-1
    ("demo-grp-02", "Egipto", "🇪🇬", "Catar", "🇶🇦"),      # finalizado 2-0
    ("demo-grp-03", "Panamá", "🇵🇦", "Honduras", "🇭🇳"),   # en juego (bloqueado)
    ("demo-grp-04", "Paraguay", "🇵🇾", "Chile", "🇨🇱"),    # más tarde (editable)
]

# Dieciseisavos de final (top 32): los 16 cruces, repartidos 4/día desde mañana.
ROUND_OF_32 = [
    ("Argentina", "🇦🇷", "Australia", "🇦🇺"),
    ("Francia", "🇫🇷", "Senegal", "🇸🇳"),
    ("Brasil", "🇧🇷", "Corea del Sur", "🇰🇷"),
    ("Inglaterra", "🏴", "Ecuador", "🇪🇨"),
    ("España", "🇪🇸", "Costa Rica", "🇨🇷"),
    ("Portugal", "🇵🇹", "Ghana", "🇬🇭"),
    ("Países Bajos", "🇳🇱", "Perú", "🇵🇪"),
    ("Alemania", "🇩🇪", "Arabia Saudita", "🇸🇦"),
    ("Italia", "🇮🇹", "Camerún", "🇨🇲"),
    ("Bélgica", "🇧🇪", "Canadá", "🇨🇦"),
    ("Croacia", "🇭🇷", "Serbia", "🇷🇸"),
    ("Uruguay", "🇺🇾", "Polonia", "🇵🇱"),
    ("Colombia", "🇨🇴", "Japón", "🇯🇵"),
    ("México", "🇲🇽", "Nigeria", "🇳🇬"),
    ("Estados Unidos", "🇺🇸", "Dinamarca", "🇩🇰"),
    ("Marruecos", "🇲🇦", "Suiza", "🇨🇭"),
]

# Octavos de final (round of 16): 8 cruces con equipos por confirmar (TBD).
N_ROUND_OF_16 = 8

KICKOFF_HOURS_ES = [10, 13, 16, 19]  # 4 partidos por día


def _build_matches(today, tomorrow):
    """Construye los partidos de demostración.

    - HOY: cierre de fase de grupos (2 finalizados, 1 en juego, 1 editable).
    - DESDE MAÑANA: los 16 dieciseisavos, 4 por día durante 4 días.
    - DESPUÉS: 8 octavos con equipos TBD para completar el bracket.
    """
    now = datetime.now(UTC)
    matches: list[dict] = []

    # ── HOY: cierre de grupos ──
    g1, g2, g3, g4 = GROUP_TODAY
    matches += [
        {
            "external_id": g1[0], "home": g1[1], "home_flag": g1[2],
            "away": g1[3], "away_flag": g1[4],
            "kickoff_utc": now - timedelta(hours=4), "match_date_local": today,
            "stage": "group", "status": MatchStatus.FINISHED,
            "goals_home": 1, "goals_away": 1,  # empate
        },
        {
            "external_id": g2[0], "home": g2[1], "home_flag": g2[2],
            "away": g2[3], "away_flag": g2[4],
            "kickoff_utc": now - timedelta(hours=2), "match_date_local": today,
            "stage": "group", "status": MatchStatus.FINISHED,
            "goals_home": 2, "goals_away": 0,
        },
        {
            "external_id": g3[0], "home": g3[1], "home_flag": g3[2],
            "away": g3[3], "away_flag": g3[4],
            "kickoff_utc": now - timedelta(minutes=35), "match_date_local": today,
            "stage": "group", "status": MatchStatus.LIVE,
        },
        {
            "external_id": g4[0], "home": g4[1], "home_flag": g4[2],
            "away": g4[3], "away_flag": g4[4],
            "kickoff_utc": now + timedelta(hours=3), "match_date_local": today,
            "stage": "group", "status": MatchStatus.SCHEDULED,
        },
    ]

    # ── DIECISEISAVOS: 16 partidos, 4/día desde mañana ──
    for i, (home, hflag, away, aflag) in enumerate(ROUND_OF_32):
        day = tomorrow + timedelta(days=i // 4)
        hour = KICKOFF_HOURS_ES[i % 4]
        matches.append({
            "external_id": f"demo-r32-{i + 1:02d}",
            "home": home, "home_flag": hflag,
            "away": away, "away_flag": aflag,
            "kickoff_utc": at_es(day, hour),
            "match_date_local": day,
            "stage": "knockout", "status": MatchStatus.SCHEDULED,
        })

    # ── OCTAVOS: 8 partidos TBD (equipos por confirmar), tras los dieciseisavos ──
    r16_start = tomorrow + timedelta(days=5)  # día de descanso entre rondas
    for i in range(N_ROUND_OF_16):
        day = r16_start + timedelta(days=i // 4)
        hour = KICKOFF_HOURS_ES[i % 4]
        matches.append({
            "external_id": f"demo-r16-{i + 1:02d}",
            "home": None, "home_flag": None,
            "away": None, "away_flag": None,
            "kickoff_utc": at_es(day, hour),
            "match_date_local": day,
            "stage": "knockout", "status": MatchStatus.SCHEDULED,
        })

    return matches


# Predicciones de partidos FINALIZADOS, por nombre de jugador.
# (external_id → (pred_home, pred_away)). Reales: grp-01 = 1-1, grp-02 = 2-0.
FINISHED_PREDICTIONS = {
    "Cuestas":  {"demo-grp-01": (1, 1), "demo-grp-02": (2, 0)},  # 4 + 4 = 8
    "Vega":     {"demo-grp-01": (0, 0), "demo-grp-02": (1, 0)},  # 2 + 2 = 4
    "Chepe":    {"demo-grp-01": (2, 0), "demo-grp-02": (0, 2)},  # 0 + 0 = 0
    "Mamer":    {"demo-grp-01": (1, 1), "demo-grp-02": (3, 1)},  # 4 + 2 = 6
    "Josue":    {"demo-grp-01": (1, 1), "demo-grp-02": (0, 0)},  # 4 + 0 = 4
    "Tony":     {"demo-grp-01": (2, 2), "demo-grp-02": (1, 1)},  # 2 + 0 = 2
    "Colocha":  {"demo-grp-01": (1, 1)},                          # 4 (+0 sin pred) = 4
    "Jaime":    {"demo-grp-01": (1, 1)},                          # 4 (+0 sin pred) = 4
    # Frank, Mumuja, Chicapan: sin predicciones → 0 puntos por partido (= 0)
}

# Predicciones de dieciseisavos (programados) para mostrar "Editar" vs "Guardar".
SCHEDULED_PREDICTIONS = {
    "Cuestas": {"demo-r32-01": (2, 0), "demo-r32-04": (1, 1)},
    "Josue":   {"demo-r32-02": (3, 0)},
    "Vega":    {"demo-r32-03": (1, 2)},
    "Mamer":   {"demo-r32-01": (1, 1)},
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
                initial_points=p.get("initial_points", 0),
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
    print(f"   Hoy ES: {today} (cierre de grupos)  |  Mañana ES: {tomorrow} (inician dieciseisavos)")
    print(f"   Dieciseisavos: {len(ROUND_OF_32)} partidos del {tomorrow} al {tomorrow + timedelta(days=3)}")
    print(f"   Octavos (TBD): {N_ROUND_OF_16} partidos desde {tomorrow + timedelta(days=5)}")
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
