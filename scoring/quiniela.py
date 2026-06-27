"""Módulo puro de puntuación para quiniela de fútbol.

Funciones:
  outcome(home, away) -> 'H' | 'A' | 'D'
  score(pred_home, pred_away, res_home, res_away) -> 1 | 2 | 3

Reglas:
  - Exacto = 3 puntos
  - Resultado correcto (mismo outcome, distinto marcador) = 2 puntos
  - Incorrecto = 1 punto
  - Sin predicción = 1 punto

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
        3 = acierto exacto del marcador.
        2 = resultado acertado (mismo outcome), pero marcador distinto.
        1 = resultado incorrecto o sin predicción.
    """
    # Sin predicción
    if pred_home is None or pred_away is None:
        return 1

    # Marcador exacto
    if pred_home == res_home and pred_away == res_away:
        return 3

    # Mismo outcome
    if outcome(pred_home, pred_away) == outcome(res_home, res_away):
        return 2

    # Incorrecto
    return 1
