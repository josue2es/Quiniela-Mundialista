"""Tests para auth/lockout.py — bloqueo por IP + desbloqueo por el admin."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from data.models import Base, LoginAttempt
from auth.lockout import (
    MAX_FAILED_ATTEMPTS,
    LOCKOUT_MINUTES,
    is_locked,
    lock_remaining_minutes,
    locked_ips,
    register_failure,
    register_success,
    remaining_attempts,
    unlock_ip,
)

IP = "203.0.113.7"


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


class TestRegisterFailure:
    def test_below_threshold_not_locked(self, db_session):
        with db_session() as s:
            for _ in range(MAX_FAILED_ATTEMPTS - 1):
                assert register_failure(s, IP) is False
            s.commit()
            assert not is_locked(s, IP)
            assert remaining_attempts(s, IP) == 1

    def test_threshold_locks(self, db_session):
        with db_session() as s:
            results = [register_failure(s, IP) for _ in range(MAX_FAILED_ATTEMPTS)]
            s.commit()
            assert results[-1] is True
            assert results[:-1] == [False] * (MAX_FAILED_ATTEMPTS - 1)
            assert is_locked(s, IP)
            row = s.query(LoginAttempt).filter_by(ip=IP).one()
            assert row.failed_attempts == 0  # se resetea al bloquear
            assert row.locked_until is not None

    def test_failures_are_per_ip(self, db_session):
        other = "198.51.100.42"
        with db_session() as s:
            for _ in range(MAX_FAILED_ATTEMPTS):
                register_failure(s, IP)
            s.commit()
            assert is_locked(s, IP)
            assert not is_locked(s, other)  # otra IP no se ve afectada

    def test_remaining_attempts_no_row(self, db_session):
        with db_session() as s:
            assert remaining_attempts(s, "10.0.0.1") == MAX_FAILED_ATTEMPTS


class TestLockTiming:
    def test_lock_remaining_minutes(self, db_session):
        with db_session() as s:
            for _ in range(MAX_FAILED_ATTEMPTS):
                register_failure(s, IP)
            s.commit()
            assert 1 <= lock_remaining_minutes(s, IP) <= LOCKOUT_MINUTES

    def test_expired_lock_not_locked(self, db_session):
        with db_session() as s:
            s.add(LoginAttempt(ip=IP, failed_attempts=0,
                               locked_until=datetime.utcnow() - timedelta(minutes=1)))
            s.commit()
            assert not is_locked(s, IP)
            assert lock_remaining_minutes(s, IP) == 0


class TestSuccessAndUnlock:
    def test_register_success_clears(self, db_session):
        with db_session() as s:
            register_failure(s, IP)
            register_success(s, IP)
            s.commit()
            row = s.query(LoginAttempt).filter_by(ip=IP).one()
            assert row.failed_attempts == 0
            assert row.locked_until is None

    def test_register_success_no_row_is_noop(self, db_session):
        with db_session() as s:
            register_success(s, "10.0.0.99")  # no debe explotar
            s.commit()
            assert s.query(LoginAttempt).count() == 0

    def test_unlock_ip(self, db_session):
        with db_session() as s:
            for _ in range(MAX_FAILED_ATTEMPTS):
                register_failure(s, IP)
            s.commit()
            assert is_locked(s, IP)

        assert unlock_ip(IP, db_session) is True

        with db_session() as s:
            assert not is_locked(s, IP)

    def test_unlock_missing_ip(self, db_session):
        assert unlock_ip("8.8.8.8", db_session) is False

    def test_locked_ips_lists_only_locked(self, db_session):
        with db_session() as s:
            s.add(LoginAttempt(ip="1.1.1.1", failed_attempts=0,
                               locked_until=datetime.utcnow() + timedelta(minutes=30)))
            s.add(LoginAttempt(ip="2.2.2.2", failed_attempts=0,
                               locked_until=datetime.utcnow() - timedelta(minutes=1)))
            s.add(LoginAttempt(ip="3.3.3.3", failed_attempts=2))
            s.commit()

        ips = {r["ip"] for r in locked_ips(db_session)}
        assert ips == {"1.1.1.1"}
