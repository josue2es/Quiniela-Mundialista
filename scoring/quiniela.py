"""Módulo puro de puntuación para quiniela de fútbol.

Funciones:
  outcome(home, away) -> 'H' | 'A' | 'D'
  score(pred_home, pred_away, res_home, res_away) -> 0 | 2 | 4

Reglas:
  - Marcador exacto = 4 puntos
  - Acierta el resultado (ganador o empate), distinto marcador = 2 puntos
  - No acierta = 0 puntos
  - Sin predicción = 0 puntos

Regla de penales (ver §5):
  - El marcador (4 = exacto, 2 = mismo outcome) se calcula sobre los goles
    reglamentarios / de prórroga, SIN contar penales. Un 1-1 decidido por
    penales sigue siendo empate (D) a efectos del marcador.
  - ADEMÁS: si el partido se definió por penales (empate reglamentario con un
    ganador en la tanda), quien predijo a ESE ganador recibe 2 puntos. Es
    aditivo: no le quita puntos a quien acertó el empate o el marcador exacto.
"""

from typing import Optional


def outcome(home: int, away: int) -> str:
    """Determina el resultado de un partido a partir de los goles.

    Args:
        home: Goles del equipo local.
        away: Goles del equipo visitante.

    Returns:
        'H' si gana el local, 'A' si gana el visitante, 'D' si hay empate.

    La regla de penales se aplica por convención del llamante: siempre se
    deben pasar los goles reglamentarios/prórroga, sin incluir penales.
    """
    if home > away:
        return "H"
    if away > home:
        return "A"
    return "D"


def score(
    pred_home: Optional[int],
    pred_away: Optional[int],
    res_home: int,
    res_away: int,
    *,
    pen_home: Optional[int] = None,
    pen_away: Optional[int] = None,
) -> int:
    """Calcula los puntos obtenidos por una predicción.

    Args:
        pred_home: Goles predichos para el local (None si no hay predicción).
        pred_away: Goles predichos para el visitante (None si no hay predicción).
        res_home: Goles reales del local (reglamentarios, sin penales).
        res_away: Goles reales del visitante (reglamentarios, sin penales).
        pen_home: Goles del local en la tanda de penales (None si no hubo).
        pen_away: Goles del visitante en la tanda de penales (None si no hubo).

    Returns:
        4 = acierto exacto del marcador reglamentario.
        2 = resultado acertado (mismo outcome reglamentario), o —si el partido
            se definió por penales— acierto del ganador de la tanda.
        0 = resultado incorrecto o sin predicción.
    """
    # Sin predicción
    if pred_home is None or pred_away is None:
        return 0

    # Marcador exacto (sobre el reglamentario)
    if pred_home == res_home and pred_away == res_away:
        return 4

    pred_outcome = outcome(pred_home, pred_away)

    # Mismo outcome reglamentario (acierta ganador o empate)
    if pred_outcome == outcome(res_home, res_away):
        return 2

    # Penales: empate reglamentario con ganador en la tanda. Quien predijo a
    # ese ganador acierta el resultado del cruce → 2 puntos.
    if (
        outcome(res_home, res_away) == "D"
        and pen_home is not None
        and pen_away is not None
        and pen_home != pen_away
    ):
        pen_outcome = "H" if pen_home > pen_away else "A"
        if pred_outcome == pen_outcome:
            return 2

    # No acierta
    return 0
