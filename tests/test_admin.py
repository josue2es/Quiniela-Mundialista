"""Tests para ui/admin.apply_correction — re-scoring explícito de admin.

Cubre:
  - Corregir una predicción existente recalcula y reemplaza el MatchScore.
  - Crear predicción donde no había (upsert) y puntuar.
  - Se registra una fila en admin_audit_log con old/new pred y puntos.
  - Rechazo si el usuario no es admin, si el partido no está cerrado, o rango inválido.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from data.models import (
    AdminAuditLog,
    Base,
    Match,
    MatchScore,
    MatchStatus,
    Player,
    Prediction,
)
from ui.admin import apply_correction


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(
        bind=engine, autoflush=False, autocommit=False, expire_on_commit=False
    )
    yield SessionLocal
    Base.metadata.drop_all(engine)


@pytest.fixture
def setup(db_session):
    """Un admin (Josue), un jugador normal (Vega) y un partido cerrado 2-1."""
    with db_session() as s:
        admin = Player(name="Josue", password="5678", is_admin=True, is_setup=True)
        player = Player(name="Vega", password="2345", is_setup=True)
        match = Match(
            external_id="9001",
            home="España",
            away="Alemania",
            status=MatchStatus.FINISHED,
            goals_home=2,
            goals_away=1,
            kickoff_utc=datetime(2026, 6, 26, 16, 0, tzinfo=timezone.utc),
        )
        s.add_all([admin, player, match])
        s.commit()
        return {"admin_id": admin.id, "player_id": player.id, "match_id": match.id}


def test_correct_existing_prediction_rescore(db_session, setup):
    # Vega tenía 0-0 (resultado equivocado → 0 pts)
    with db_session() as s:
        s.add(Prediction(player_id=setup["player_id"], match_id=setup["match_id"],
                         pred_home=0, pred_away=0))
        s.add(MatchScore(player_id=setup["player_id"], match_id=setup["match_id"],
                        points=0))
        s.commit()

    # Admin corrige a 2-1 (marcador exacto → 4 pts)
    res = apply_correction(
        admin_id=setup["admin_id"], match_id=setup["match_id"],
        player_id=setup["player_id"], new_home=2, new_away=1,
        session_factory=db_session,
    )

    assert res["old_points"] == 0
    assert res["new_points"] == 4

    with db_session() as s:
        scores = s.query(MatchScore).filter_by(
            player_id=setup["player_id"], match_id=setup["match_id"]
        ).all()
        assert len(scores) == 1           # no duplica
        assert scores[0].points == 4      # re-puntuado
        pred = s.query(Prediction).filter_by(
            player_id=setup["player_id"], match_id=setup["match_id"]
        ).one()
        assert (pred.pred_home, pred.pred_away) == (2, 1)


def test_create_prediction_where_none(db_session, setup):
    # Vega no tenía predicción ni score
    res = apply_correction(
        admin_id=setup["admin_id"], match_id=setup["match_id"],
        player_id=setup["player_id"], new_home=3, new_away=0,  # gana local → 2 pts
        session_factory=db_session,
    )
    assert res["old_pred"] == (None, None)
    assert res["old_points"] is None
    assert res["new_points"] == 2

    with db_session() as s:
        assert s.query(MatchScore).filter_by(
            player_id=setup["player_id"], match_id=setup["match_id"]
        ).count() == 1


def test_audit_log_written(db_session, setup):
    apply_correction(
        admin_id=setup["admin_id"], match_id=setup["match_id"],
        player_id=setup["player_id"], new_home=2, new_away=1,
        session_factory=db_session,
    )
    with db_session() as s:
        logs = s.query(AdminAuditLog).all()
        assert len(logs) == 1
        log = logs[0]
        assert log.admin_id == setup["admin_id"]
        assert log.player_id == setup["player_id"]
        assert (log.new_pred_home, log.new_pred_away) == (2, 1)
        assert log.new_points == 4


def test_rejects_non_admin(db_session, setup):
    with pytest.raises(ValueError, match="admin"):
        apply_correction(
            admin_id=setup["player_id"],  # Vega no es admin
            match_id=setup["match_id"], player_id=setup["player_id"],
            new_home=1, new_away=1, session_factory=db_session,
        )


def test_rejects_out_of_range(db_session, setup):
    with pytest.raises(ValueError):
        apply_correction(
            admin_id=setup["admin_id"], match_id=setup["match_id"],
            player_id=setup["player_id"], new_home=101, new_away=0,
            session_factory=db_session,
        )


def test_rejects_open_match(db_session, setup):
    with db_session() as s:
        open_match = Match(external_id="9002", home="A", away="B",
                          status=MatchStatus.SCHEDULED)
        s.add(open_match)
        s.commit()
        open_id = open_match.id
    with pytest.raises(ValueError, match="cerrado"):
        apply_correction(
            admin_id=setup["admin_id"], match_id=open_id,
            player_id=setup["player_id"], new_home=1, new_away=0,
            session_factory=db_session,
        )
