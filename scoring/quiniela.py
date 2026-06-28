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
  - Se usan goles reglamentarios / de prórroga, SIN contar penales.
  - Un 1-1 decidido por penales cuenta como empate (D).
  - El score se calcula sobre el marcador reglamentario.
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
) -> int:
    """Calcula los puntos obtenidos por una predicción.

    Args:
        pred_home: Goles predichos para el local (None si no hay predicción).
        pred_away: Goles predichos para el visitante (None si no hay predicción).
        res_home: Goles reales del local (reglamentarios, sin penales).
        res_away: Goles reales del visitante (reglamentarios, sin penales).

    Returns:
        4 = acierto exacto del marcador.
        2 = resultado acertado (mismo outcome), pero marcador distinto.
        0 = resultado incorrecto o sin predicción.
    """
    # Sin predicción
    if pred_home is None or pred_away is None:
        return 0

    # Marcador exacto
    if pred_home == res_home and pred_away == res_away:
        return 4

    # Mismo outcome (acierta ganador o empate)
    if outcome(pred_home, pred_away) == outcome(res_home, res_away):
        return 2

    # No acierta
    return 0
