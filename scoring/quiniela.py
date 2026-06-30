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
  - Si el partido se definió por penales (empate reglamentario con un ganador
    en la tanda), la tanda DEFINE el resultado: es como una victoria pura del
    que ganó los penales. Sólo quien predijo a ESE ganador puntúa (2 puntos);
    quien predijo empate recibe 0, incluso si acertó el marcador reglamentario
    exacto.
  - Sin penales, el marcador normal: 4 = marcador exacto, 2 = mismo outcome.
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
        En partidos definidos por penales: 2 si predijo al ganador de la tanda,
        0 en caso contrario (predecir empate ya no puntúa).
        En el resto: 4 = marcador exacto, 2 = mismo outcome, 0 = no acierta.
        Sin predicción siempre 0.
    """
    # Sin predicción
    if pred_home is None or pred_away is None:
        return 0

    pred_outcome = outcome(pred_home, pred_away)

    # Penales: empate reglamentario con ganador en la tanda. La tanda define el
    # resultado (victoria pura del ganador): sólo quien predijo a ese ganador
    # puntúa (2). Predecir empate —aun el marcador exacto— recibe 0.
    if (
        outcome(res_home, res_away) == "D"
        and pen_home is not None
        and pen_away is not None
        and pen_home != pen_away
    ):
        pen_outcome = "H" if pen_home > pen_away else "A"
        return 2 if pred_outcome == pen_outcome else 0

    # Marcador exacto (sobre el reglamentario)
    if pred_home == res_home and pred_away == res_away:
        return 4

    # Mismo outcome reglamentario (acierta ganador o empate)
    if pred_outcome == outcome(res_home, res_away):
        return 2

    # No acierta
    return 0
