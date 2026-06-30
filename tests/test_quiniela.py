"""Tests para scoring/quiniela.py — §5 de la spec.

Cubre los casos mínimos requeridos:
  - Marcador exacto → 4
  - Resultado correcto, marcador distinto → 2
  - Resultado incorrecto → 0
  - Sin predicción → 0
  - Empate exacto → 4
  - Penales (empate reglamentario) → según marcador
"""

import pytest
from scoring.quiniela import outcome, score


class TestOutcome:
    def test_home_wins(self):
        assert outcome(2, 0) == "H"
        assert outcome(3, 1) == "H"

    def test_away_wins(self):
        assert outcome(0, 1) == "A"
        assert outcome(1, 3) == "A"

    def test_draw(self):
        assert outcome(1, 1) == "D"
        assert outcome(0, 0) == "D"
        # Penales: 1-1 reglamentario sigue siendo empate
        assert outcome(1, 1) == "D"

    def test_high_scores(self):
        assert outcome(5, 4) == "H"
        assert outcome(3, 7) == "A"


class TestScore:
    # ── Caso 1: Marcador exacto → 4 ──
    def test_exact_match_home_win(self):
        assert score(2, 0, 2, 0) == 4

    def test_exact_match_away_win(self):
        assert score(1, 3, 1, 3) == 4

    def test_exact_draw(self):
        assert score(2, 2, 2, 2) == 4

    # ── Caso 2: Resultado correcto, marcador distinto → 2 ──
    def test_correct_outcome_different_score_home(self):
        # Predice 3-0, real 2-0 → ambos son H
        assert score(3, 0, 2, 0) == 2

    def test_correct_outcome_different_score_away(self):
        # Predice 0-1, real 0-3 → ambos son A
        assert score(0, 1, 0, 3) == 2

    def test_correct_outcome_different_score_draw(self):
        # Predice 0-0, real 1-1 → ambos son D
        assert score(0, 0, 1, 1) == 2

    # ── Caso 3: Resultado incorrecto → 0 ──
    def test_wrong_outcome_predicted_home_real_away(self):
        assert score(2, 0, 0, 1) == 0

    def test_wrong_outcome_predicted_away_real_home(self):
        assert score(0, 1, 3, 0) == 0

    def test_wrong_outcome_predicted_draw_real_home(self):
        assert score(1, 1, 2, 0) == 0

    # ── Caso 4: Sin predicción → 0 ──
    def test_no_prediction_home_none(self):
        assert score(None, 0, 2, 0) == 0

    def test_no_prediction_away_none(self):
        assert score(2, None, 2, 0) == 0

    def test_no_prediction_both_none(self):
        assert score(None, None, 1, 1) == 0

    # ── Caso 5: Empate exacto (ya cubierto en test_exact_draw) ──

    # ── Caso 6: Penales — empate reglamentario → ──
    def test_penalties_draw_exact_prediction(self):
        """Partido 1-1 reglamentario, penales lo decide. Marcador reglamentario = empate."""
        # Predicción exacta del marcador reglamentario → 4
        assert score(1, 1, 1, 1) == 4

    def test_penalties_draw_wrong_margin(self):
        """Partido 1-1 reglamentario. Predijo empate pero distinto marcador → 2."""
        assert score(0, 0, 1, 1) == 2

    def test_penalties_draw_wrong_outcome(self):
        """1-1 reglamentario, sin datos de penales. Predijo victoria local → 0."""
        assert score(2, 1, 1, 1) == 0


class TestPenaltyWinner:
    """Penales (regla estricta): la tanda define el resultado.

    Sólo quien predijo al ganador de la tanda puntúa (2). Predecir empate —aun
    el marcador reglamentario exacto— recibe 0.
    """

    def test_predicted_home_win_home_wins_pens(self):
        # Predijo 2-1 (local). Reglamentario 1-1, local gana 4-3 en penales → 2.
        assert score(2, 1, 1, 1, pen_home=4, pen_away=3) == 2

    def test_predicted_away_win_away_wins_pens(self):
        # Predijo 0-2 (visitante). Reglamentario 1-1, visitante gana penales → 2.
        assert score(0, 2, 1, 1, pen_home=3, pen_away=5) == 2

    def test_predicted_home_but_away_wins_pens(self):
        # Predijo local, pero el visitante ganó la tanda → 0.
        assert score(2, 1, 1, 1, pen_home=2, pen_away=4) == 0

    def test_predicted_away_but_home_wins_pens(self):
        # Predijo visitante, pero el local ganó la tanda → 0.
        assert score(1, 2, 1, 1, pen_home=5, pen_away=4) == 0

    def test_draw_prediction_scores_zero_with_pens(self):
        # Estricto: predecir empate ya no puntúa si hubo definición por penales.
        assert score(0, 0, 1, 1, pen_home=4, pen_away=3) == 0

    def test_exact_regulation_draw_scores_zero_with_pens(self):
        # Estricto: ni siquiera el marcador reglamentario exacto puntúa.
        assert score(1, 1, 1, 1, pen_home=4, pen_away=3) == 0

    def test_regulation_win_unaffected_by_pen_args(self):
        # Si NO hubo empate reglamentario, los penales son irrelevantes.
        assert score(2, 0, 2, 0, pen_home=1, pen_away=0) == 4
        assert score(3, 0, 2, 0, pen_home=1, pen_away=0) == 2

    # ── Edge cases ──
    def test_zero_zero_exact(self):
        assert score(0, 0, 0, 0) == 4

    def test_high_scoring_game_exact(self):
        assert score(5, 4, 5, 4) == 4

    def test_high_scoring_game_correct_outcome(self):
        assert score(5, 3, 4, 1) == 2
