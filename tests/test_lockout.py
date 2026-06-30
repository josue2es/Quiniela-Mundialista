"""Tests para auth/lockout.py — bloqueo por intentos fallidos + desbloqueo admin."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from data.models import Base, Player
from auth.lockout import (
    MAX_FAILED_ATTEMPTS,
    LOCKOUT_MINUTES,
    is_locked,
    lock_remaining_minutes,
    locked_players,
    register_failure,
    register_success,
    remaining_attempts,
    unlock_player,
)


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:", echo=False)

    @event.listens_for(engine, "connect")
    def _on_connect(dbapi_conn, _rec):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON;")
        cur.close()

    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(
        bind=engine, autoflush=False, autocommit=False, expire_on_commit=False
    )
    yield SessionLocal
    Base.metadata.drop_all(engine)


@pytest.fixture
def player(db_session):
    with db_session() as s:
        p = Player(name="Cuestas", password="1234")
        s.add(p)
        s.commit()
        return p.id


class TestRegisterFailure:
    def test_below_threshold_not_locked(self, db_session, player):
        with db_session() as s:
            p = s.get(Player, player)
            for _ in range(MAX_FAILED_ATTEMPTS - 1):
                locked = register_failure(s, p)
                assert locked is False
            s.commit()
            assert p.failed_attempts == MAX_FAILED_ATTEMPTS - 1
            assert not is_locked(p)

    def test_threshold_locks(self, db_session, player):
        with db_session() as s:
            p = s.get(Player, player)
            results = [register_failure(s, p) for _ in range(MAX_FAILED_ATTEMPTS)]
            s.commit()
            # Sólo el último fallo dispara el bloqueo.
            assert results[-1] is True
            assert results[:-1] == [False] * (MAX_FAILED_ATTEMPTS - 1)
            assert is_locked(p)
            # Al bloquear se resetea el contador (el candado es la barrera).
            assert p.failed_attempts == 0
            assert p.locked_until is not None

    def test_remaining_attempts(self, db_session, player):
        with db_session() as s:
            p = s.get(Player, player)
            assert remaining_attempts(p) == MAX_FAILED_ATTEMPTS
            register_failure(s, p)
            assert remaining_attempts(p) == MAX_FAILED_ATTEMPTS - 1


class TestLockTiming:
    def test_lock_remaining_minutes(self, db_session, player):
        with db_session() as s:
            p = s.get(Player, player)
            for _ in range(MAX_FAILED_ATTEMPTS):
                register_failure(s, p)
            s.commit()
            mins = lock_remaining_minutes(p)
            assert 1 <= mins <= LOCKOUT_MINUTES

    def test_expired_lock_not_locked(self, db_session, player):
        with db_session() as s:
            p = s.get(Player, player)
            p.locked_until = datetime.utcnow() - timedelta(minutes=1)
            s.commit()
            assert not is_locked(p)
            assert lock_remaining_minutes(p) == 0

    def test_future_lock_is_locked(self, db_session, player):
        with db_session() as s:
            p = s.get(Player, player)
            p.locked_until = datetime.utcnow() + timedelta(minutes=30)
            s.commit()
            assert is_locked(p)


class TestSuccessAndUnlock:
    def test_register_success_clears(self, db_session, player):
        with db_session() as s:
            p = s.get(Player, player)
            register_failure(s, p)
            register_success(p)
            s.commit()
            assert p.failed_attempts == 0
            assert p.locked_until is None

    def test_unlock_player(self, db_session, player):
        with db_session() as s:
            p = s.get(Player, player)
            for _ in range(MAX_FAILED_ATTEMPTS):
                register_failure(s, p)
            s.commit()
            assert is_locked(p)

        assert unlock_player(player, db_session) is True

        with db_session() as s:
            p = s.get(Player, player)
            assert not is_locked(p)
            assert p.failed_attempts == 0
            assert p.locked_until is None

    def test_unlock_missing_player(self, db_session):
        assert unlock_player(9999, db_session) is False

    def test_locked_players_lists_only_locked(self, db_session):
        with db_session() as s:
            locked = Player(
                name="Bloqueado",
                password="1",
                locked_until=datetime.utcnow() + timedelta(minutes=30),
            )
            expired = Player(
                name="Expirado",
                password="1",
                locked_until=datetime.utcnow() - timedelta(minutes=1),
            )
            normal = Player(name="Normal", password="1")
            s.add_all([locked, expired, normal])
            s.commit()

        rows = locked_players(db_session)
        names = {r["name"] for r in rows}
        assert names == {"Bloqueado"}
