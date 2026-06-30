#!/usr/bin/env python3
"""Back-fill de penales + re-puntuación de partidos definidos por tanda.

Para partidos ya FINISHED que terminaron empatados en tiempo reglamentario y
se puntuaron ANTES de que el sistema tuviera en cuenta la tanda de penales.
Re-consulta al proveedor, guarda pen_home/pen_away en el partido y re-puntúa a
los 11 jugadores con la regla vigente (la tanda define el resultado: sólo quien
predijo al ganador de los penales recibe 2 puntos).

Sólo revisa partidos con empate reglamentario (goals_home == goals_away): son
los únicos que pudieron definirse por penales. Si el proveedor no reporta
penales para un partido (empate real, p.ej. de fase de grupos), se deja igual.

Uso:
    uv run python scripts/backfill_penalties.py            # aplica cambios
    uv run python scripts/backfill_penalties.py --dry-run  # sólo muestra
    uv run python scripts/backfill_penalties.py --match-id 123  # un partido
    uv run python scripts/backfill_penalties.py --force    # re-chequea aunque
                                                           # ya tenga datos de penales

Requiere APIFOOTBALL_KEY en el entorno (igual que el scheduler).
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

# ── Project setup ────────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from data.database import SessionLocal, init_db  # noqa: E402
from data.models import Match, MatchScore, MatchStatus, Player, Prediction  # noqa: E402
from scoring.quiniela import score as compute_score  # noqa: E402


def _draw_candidates(session, *, match_id: int | None, force: bool) -> list[Match]:
    """Partidos FINISHED con empate reglamentario (posibles penales).

    Por defecto sólo los que aún no tienen datos de penales (pen_home NULL).
    Con --force se revisan todos; con --match-id se acota a uno.
    """
    q = session.query(Match).filter(
        Match.status == MatchStatus.FINISHED,
        Match.goals_home.isnot(None),
        Match.goals_away.isnot(None),
        Match.goals_home == Match.goals_away,
    )
    if match_id is not None:
        q = q.filter(Match.id == match_id)
    elif not force:
        q = q.filter(Match.pen_home.is_(None))
    return q.order_by(Match.kickoff_utc).all()


def _rescore_match(session, match: Match, pen_home: int, pen_away: int) -> None:
    """Borra los MatchScore previos del partido y recalcula los 11 jugadores."""
    session.query(MatchScore).filter_by(match_id=match.id).delete()

    players = session.query(Player).all()
    preds = {
        p.player_id: p
        for p in session.query(Prediction).filter_by(match_id=match.id).all()
    }
    for player in players:
        pred = preds.get(player.id)
        if pred is not None:
            pts = compute_score(
                pred.pred_home,
                pred.pred_away,
                match.goals_home,
                match.goals_away,
                pen_home=pen_home,
                pen_away=pen_away,
            )
        else:
            pts = 0
        session.add(MatchScore(player_id=player.id, match_id=match.id, points=pts))


async def backfill(*, match_id: int | None, force: bool, dry_run: bool) -> int:
    """Devuelve cuántos partidos se actualizaron (0 en dry-run)."""
    # Snapshot de candidatos (fuera del provider, sesión corta)
    with SessionLocal() as session:
        candidates = _draw_candidates(session, match_id=match_id, force=force)
        cand = [
            {
                "id": m.id,
                "external_id": m.external_id,
                "home": m.home or "TBD",
                "away": m.away or "TBD",
                "goals_home": m.goals_home,
                "goals_away": m.goals_away,
            }
            for m in candidates
        ]

    if not cand:
        print("backfill: no hay partidos con empate reglamentario para revisar.")
        return 0

    print(
        f"backfill: {len(cand)} partido(s) empatado(s) a revisar contra el proveedor..."
    )

    # Importar acá para que --help no exija APIFOOTBALL_KEY
    from provider.api_football import ApiFootballProvider

    ext_ids = [c["external_id"] for c in cand]
    try:
        async with ApiFootballProvider() as provider:
            results = await provider.fetch_results(ext_ids)
    except ValueError as e:
        print(f"backfill ERROR: {e}", file=sys.stderr)
        return 0

    result_map = {r.external_id: r for r in results}

    updated = 0
    with SessionLocal() as session:
        for c in cand:
            label = f"{c['home']} {c['goals_home']}-{c['goals_away']} {c['away']}"
            r = result_map.get(c["external_id"])
            if r is None:
                print(f"  · {label}: el proveedor no devolvió datos, se salta.")
                continue

            pen_home = getattr(r, "pen_home", None)
            pen_away = getattr(r, "pen_away", None)
            if pen_home is None or pen_away is None or pen_home == pen_away:
                print(f"  · {label}: sin definición por penales, se deja igual.")
                continue

            winner = c["home"] if pen_home > pen_away else c["away"]
            print(
                f"  ✔ {label} (pen {pen_home}-{pen_away}, gana {winner}) → re-puntuar"
            )
            if dry_run:
                continue

            match = session.get(Match, c["id"])
            match.pen_home = pen_home
            match.pen_away = pen_away
            _rescore_match(session, match, pen_home, pen_away)
            updated += 1

        if not dry_run:
            session.commit()

    if dry_run:
        print("backfill: dry-run, no se guardó nada.")
    else:
        print(f"backfill: {updated} partido(s) actualizado(s) y re-puntuado(s).")
    return updated


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Back-fill de penales y re-puntuación de partidos por tanda."
    )
    parser.add_argument(
        "--match-id", type=int, default=None, help="Acota a un solo partido (por id)."
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Revisa también partidos que ya tienen datos de penales.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Muestra qué cambiaría sin escribir en la base.",
    )
    args = parser.parse_args()

    init_db()  # asegura tablas/columnas (idempotente)
    asyncio.run(
        backfill(match_id=args.match_id, force=args.force, dry_run=args.dry_run)
    )


if __name__ == "__main__":
    main()
