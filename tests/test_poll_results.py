"""Tests para scheduler/poll_results.py — puntuación al finalizar partidos.

Cubre:
  - Detección de partidos que transicionan a finished.
  - Puntuación para los 11 jugadores (con y sin predicción).
  - Idempotencia (segunda ejecución no duplica).
  - Sin partidos activos → sin side effects.
"""

from __future__ import annotations

import pytest
from dataclasses import dataclass
from datetime import date, datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from data.models import Base, Match, MatchScore, MatchStatus, Player, Prediction
from scheduler.poll_results import (
    poll_results,
    _score_match,
    _is_finished_status,
    reset_zombie_matches,
)


# ── Fake Provider ────────────────────────────────────────────────────────────

@dataclass
class FakeResult:
    external_id: str
    home_goals: int
    away_goals: int
    status: str
    pen_home: int | None = None
    pen_away: int | None = None


class FakeProvider:
    """Provider falso — devuelve resultados predefinidos para IDs conocidos."""

    def __init__(self, results: list[FakeResult] | None = None):
        self._results = results or []
        self._calls: list[list[str]] = []  # registra cada llamada a fetch_results

    async def fetch_results(self, external_ids: list[str]) -> list[FakeResult]:
        self._calls.append(list(external_ids))
        by_id = {r.external_id: r for r in self._results}
        return [by_id[eid] for eid in external_ids if eid in by_id]


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def db_session():
    """Engine + session factory en SQLite en memoria."""
    engine = create_engine("sqlite:///:memory:", echo=False)

    # Activar WAL + FK
    from sqlalchemy import event
    @event.listens_for(engine, "connect")
    def _on_connect(dbapi_conn, _rec):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL;")
        cursor.execute("PRAGMA foreign_keys=ON;")
        cursor.close()

    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)

    yield SessionLocal

    Base.metadata.drop_all(engine)


@pytest.fixture
def players(db_session):
    """Los 11 jugadores de players.csv."""
    names = [
        "Cuestas", "Vega", "Chepe", "Mamer", "Josue",
        "Tony", "Frank", "Colocha", "Mumuja", "Jaime", "Chicapan",
    ]
    with db_session() as session:
        for name in names:
            session.add(Player(name=name, password="1234", is_setup=True))
        session.commit()


@pytest.fixture
def match(db_session):
    """Partido en estado SCHEDULED."""
    with db_session() as session:
        m = Match(
            external_id="1001",
            home="Argentina",
            away="Brasil",
            status=MatchStatus.SCHEDULED,
            kickoff_utc=datetime(2026, 6, 27, 16, 0, tzinfo=timezone.utc),
        )
        session.add(m)
        session.commit()
        return m.id


@pytest.fixture
def finished_match(db_session):
    """Partido ya terminado con goles."""
    with db_session() as session:
        m = Match(
            external_id="2002",
            home="España",
            away="Alemania",
            status=MatchStatus.FINISHED,
            goals_home=2,
            goals_away=1,
            kickoff_utc=datetime(2026, 6, 26, 16, 0, tzinfo=timezone.utc),
        )
        session.add(m)
        session.commit()
        return m.id


# ── _is_finished_status ──────────────────────────────────────────────────────

class TestResetZombies:
    def test_resets_finished_without_goals(self, db_session):
        with db_session() as s:
            # Zombi: FINISHED sin goles
            s.add(Match(external_id="z1", home="Brazil", away="Japan",
                        status=MatchStatus.FINISHED, goals_home=None, goals_away=None))
            # Sano: FINISHED con goles
            s.add(Match(external_id="ok", home="A", away="B",
                        status=MatchStatus.FINISHED, goals_home=2, goals_away=1))
            # Programado normal
            s.add(Match(external_id="sch", home="C", away="D",
                        status=MatchStatus.SCHEDULED))
            s.commit()

        n = reset_zombie_matches(db_session)
        assert n == 1

        with db_session() as s:
            assert s.query(Match).filter_by(external_id="z1").one().status == MatchStatus.SCHEDULED
            assert s.query(Match).filter_by(external_id="ok").one().status == MatchStatus.FINISHED
            assert s.query(Match).filter_by(external_id="sch").one().status == MatchStatus.SCHEDULED

    def test_no_zombies_returns_zero(self, db_session):
        with db_session() as s:
            s.add(Match(external_id="ok", home="A", away="B",
                        status=MatchStatus.FINISHED, goals_home=0, goals_away=0))
            s.commit()
        assert reset_zombie_matches(db_session) == 0


class TestIsFinishedStatus:
    def test_finished(self):
        assert _is_finished_status("finished") is True

    def test_live(self):
        assert _is_finished_status("live") is False

    def test_scheduled(self):
        assert _is_finished_status("scheduled") is False


# ── _score_match ─────────────────────────────────────────────────────────────

class TestScoreMatch:
    def test_all_players_scored(self, db_session, players, match):
        """Los 11 jugadores reciben puntuación para el partido."""
        rows = _score_match(db_session, match_id=match, goals_home=2, goals_away=0)

        assert rows == 11

        # Verificar que hay 11 filas en match_scores
        with db_session() as session:
            scores = session.query(MatchScore).filter_by(match_id=match).all()
            assert len(scores) == 11

    def test_no_prediction_gets_zero_points(self, db_session, players, match):
        """Jugadores sin predicción reciben 0 puntos."""
        rows = _score_match(db_session, match_id=match, goals_home=3, goals_away=1)

        with db_session() as session:
            scores = session.query(MatchScore).filter_by(match_id=match).all()
            for s in scores:
                assert s.points == 0, f"Sin predicción, esperado 0, obtuvo {s.points}"

    def test_with_predictions_respects_scoring(self, db_session, players, match):
        """Con predicciones usa score() del módulo de scoring."""
        # Asignamos predicciones a los primeros 3 jugadores
        with db_session() as session:
            all_players = session.query(Player).all()
            preds = [
                Prediction(player_id=all_players[0].id, match_id=match, pred_home=2, pred_away=0),  # exacto → 4
                Prediction(player_id=all_players[1].id, match_id=match, pred_home=3, pred_away=0),  # outcome H → 2
                Prediction(player_id=all_players[2].id, match_id=match, pred_home=0, pred_away=1),  # outcome A → 0
            ]
            session.add_all(preds)
            session.commit()

        # Resultado real: 2-0
        rows = _score_match(db_session, match_id=match, goals_home=2, goals_away=0)
        assert rows == 11

        with db_session() as session:
            scores = {
                s.player_id: s.points
                for s in session.query(MatchScore).filter_by(match_id=match).all()
            }

        # Jugador 0: predijo exacto 2-0 → 4 puntos
        assert scores[all_players[0].id] == 4
        # Jugador 1: predijo 3-0 (outcome H correcto) → 2 puntos
        assert scores[all_players[1].id] == 2
        # Jugador 2: predijo 0-1 (outcome A incorrecto) → 0 puntos
        assert scores[all_players[2].id] == 0
        # Jugadores 3-10: sin predicción → 0 puntos
        for i in range(3, 11):
            assert scores[all_players[i].id] == 0

    def test_idempotent(self, db_session, players, match):
        """Segunda ejecución no inserta duplicados."""
        rows1 = _score_match(db_session, match_id=match, goals_home=1, goals_away=1)
        assert rows1 == 11

        rows2 = _score_match(db_session, match_id=match, goals_home=1, goals_away=1)
        assert rows2 == 0  # todas ya existían

        with db_session() as session:
            count = session.query(MatchScore).filter_by(match_id=match).count()
            assert count == 11


# ── poll_results ─────────────────────────────────────────────────────────────

class TestPollResults:
    async def test_no_active_matches(self, db_session, finished_match):
        """Sin partidos activos → retorna 0 scored."""
        provider = FakeProvider()
        result = await poll_results(provider, db_session)
        assert result["scored_matches"] == 0
        assert result["rows_inserted"] == 0
        assert result["active_matches"] == 0

    async def test_no_results_from_provider(self, db_session, players, match):
        """Provider no devuelve datos para el partido → sin cambios."""
        provider = FakeProvider([])  # sin resultados
        result = await poll_results(provider, db_session)

        assert result["scored_matches"] == 0
        assert result["active_matches"] == 1

        # El partido sigue en SCHEDULED
        with db_session() as session:
            m = session.query(Match).filter_by(id=match).first()
            assert m.status == MatchStatus.SCHEDULED

    async def test_match_finished_and_scored(self, db_session, players, match):
        """Partido transiciona a finished → 11 filas en match_scores."""
        provider = FakeProvider([
            FakeResult(external_id="1001", home_goals=3, away_goals=0, status="finished"),
        ])

        result = await poll_results(provider, db_session)

        assert result["scored_matches"] == 1
        assert result["rows_inserted"] == 11

        # Verificar partido actualizado
        with db_session() as session:
            m = session.query(Match).filter_by(id=match).first()
            assert m.status == MatchStatus.FINISHED
            assert m.goals_home == 3
            assert m.goals_away == 0

            scores = session.query(MatchScore).filter_by(match_id=match).all()
            assert len(scores) == 11

    async def test_mixed_predictions(self, db_session, players, match):
        """Mezcla de jugadores con y sin predicción."""
        with db_session() as session:
            all_players = session.query(Player).all()
            # 5 jugadores predicen, 6 no
            for i in range(5):
                session.add(Prediction(
                    player_id=all_players[i].id,
                    match_id=match,
                    pred_home=2,
                    pred_away=1,
                ))
            session.commit()

        provider = FakeProvider([
            FakeResult(external_id="1001", home_goals=2, away_goals=1, status="finished"),
        ])

        result = await poll_results(provider, db_session)

        assert result["scored_matches"] == 1
        assert result["rows_inserted"] == 11

        with db_session() as session:
            scores = {
                s.player_id: s.points
                for s in session.query(MatchScore).filter_by(match_id=match).all()
            }

        # Los 5 con predicción exacta → 4 puntos
        for i in range(5):
            assert scores[all_players[i].id] == 4, f"Player {i}: expected 4"
        # Los 6 sin predicción → 0 puntos
        for i in range(5, 11):
            assert scores[all_players[i].id] == 0, f"Player {i}: expected 0"

    async def test_penalty_winner_scored(self, db_session, players, match):
        """1-1 reglamentario decidido por penales: quien predijo al ganador → 2."""
        with db_session() as session:
            all_players = session.query(Player).all()
            # Jugador 0 predijo victoria local (2-1); local gana la tanda → 2.
            session.add(Prediction(
                player_id=all_players[0].id, match_id=match,
                pred_home=2, pred_away=1,
            ))
            # Jugador 1 predijo victoria visitante (0-1); pierde la tanda → 0.
            session.add(Prediction(
                player_id=all_players[1].id, match_id=match,
                pred_home=0, pred_away=1,
            ))
            # Jugador 2 predijo empate 1-1 (marcador reglamentario exacto). Con
            # la regla estricta de penales, el empate ya no puntúa → 0.
            session.add(Prediction(
                player_id=all_players[2].id, match_id=match,
                pred_home=1, pred_away=1,
            ))
            session.commit()

        provider = FakeProvider([
            FakeResult(external_id="1001", home_goals=1, away_goals=1,
                       status="finished", pen_home=4, pen_away=3),
        ])

        result = await poll_results(provider, db_session)
        assert result["scored_matches"] == 1

        with db_session() as session:
            m = session.query(Match).filter_by(id=match).first()
            assert m.pen_home == 4
            assert m.pen_away == 3
            scores = {
                s.player_id: s.points
                for s in session.query(MatchScore).filter_by(match_id=match).all()
            }
        assert scores[all_players[0].id] == 2  # acertó al ganador de penales
        assert scores[all_players[1].id] == 0  # ganador equivocado
        assert scores[all_players[2].id] == 0  # predijo empate: ya no puntúa

    async def test_idempotent_full_flow(self, db_session, players, match):
        """Ejecutar poll_results dos veces no duplica."""
        provider = FakeProvider([
            FakeResult(external_id="1001", home_goals=1, away_goals=1, status="finished"),
        ])

        r1 = await poll_results(provider, db_session)
        assert r1["scored_matches"] == 1
        assert r1["rows_inserted"] == 11

        r2 = await poll_results(provider, db_session)
        assert r2["scored_matches"] == 0  # ya estaba finished
        assert r2["rows_inserted"] == 0

        with db_session() as session:
            count = session.query(MatchScore).filter_by(match_id=match).count()
            assert count == 11

    async def test_skips_already_finished(self, db_session, finished_match):
        """Partido ya FINISHED no se re-procesa."""
        provider = FakeProvider([
            FakeResult(external_id="2002", home_goals=5, away_goals=0, status="finished"),
        ])

        result = await poll_results(provider, db_session)

        assert result["scored_matches"] == 0
        assert result["active_matches"] == 0  # no se consulta porque no hay activos

    async def test_live_status_not_finished(self, db_session, players, match):
        """Provider devuelve status='live' → no se marca como finished."""
        provider = FakeProvider([
            FakeResult(external_id="1001", home_goals=1, away_goals=0, status="live"),
        ])

        result = await poll_results(provider, db_session)

        assert result["scored_matches"] == 0
        assert result["rows_inserted"] == 0

        with db_session() as session:
            m = session.query(Match).filter_by(id=match).first()
            assert m.status == MatchStatus.SCHEDULED  # sin cambios

    async def test_provider_called_with_active_ids(self, db_session, players, match):
        """Provider recibe solo los IDs de partidos activos."""
        provider = FakeProvider([
            FakeResult(external_id="1001", home_goals=2, away_goals=0, status="finished"),
        ])

        await poll_results(provider, db_session)

        assert len(provider._calls) == 1
        assert provider._calls[0] == ["1001"]
