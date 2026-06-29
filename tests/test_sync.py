"""Test de regresión para scheduler/sync.py.

Bug en producción: pm.kickoff_utc (provider) es aware, existing.kickoff_utc
(SQLite) es naive → `TypeError: can't subtract offset-naive and offset-aware
datetimes` tumbaba toda la sync. Acá verificamos que un match existente con
kickoff naive se actualiza sin explotar cuando el provider trae aware.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from data.models import Base, Match, MatchStatus
from provider.models import ProviderMatch
from scheduler.sync import sync_fixtures


@dataclass
class FakeProvider:
    fixtures: list

    async def fetch_fixtures(self, since: date, until: date):
        return list(self.fixtures)

    async def fetch_results(self, external_ids):
        return []


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(
        bind=engine, autoflush=False, autocommit=False, expire_on_commit=False
    )
    yield SessionLocal
    Base.metadata.drop_all(engine)


async def test_naive_db_vs_aware_provider_no_typeerror(db_session):
    today = date(2026, 6, 28)
    # Existing match con kickoff NAIVE (como lo devuelve SQLite)
    with db_session() as s:
        s.add(
            Match(
                external_id="700",
                home="South Africa",
                away="Canada",
                status=MatchStatus.SCHEDULED,
                kickoff_utc=datetime(2026, 6, 28, 19, 0),  # naive
                match_date_local=today,
            )
        )
        s.commit()

    # Provider trae el mismo fixture con kickoff AWARE, 2 min después (>60s)
    provider = FakeProvider(
        fixtures=[
            ProviderMatch(
                external_id="700",
                home_team="South Africa",
                away_team="Canada",
                home_flag="https://x/1.png",
                away_flag="https://x/2.png",
                kickoff_utc=datetime(2026, 6, 28, 19, 2, tzinfo=timezone.utc),
                stage="Round of 32",
                status="scheduled",
            )
        ]
    )

    # No debe lanzar TypeError; debe actualizar el match.
    result = await sync_fixtures(provider, db_session, today=today, force=True)

    assert result["updated"] == 1
    with db_session() as s:
        m = s.query(Match).filter_by(external_id="700").one()
        assert m.home_flag == "https://x/1.png"


async def test_one_bad_fixture_does_not_abort_others(db_session):
    """Un fixture con kickoff inválido se salta; los buenos igual entran."""
    today = date(2026, 6, 28)

    class BadKickoff:
        """kickoff_utc explota al usarse en operaciones de fecha."""
        tzinfo = None

        def astimezone(self, *a, **k):
            raise ValueError("kickoff roto")

    good = ProviderMatch(
        external_id="800", home_team="A", away_team="B",
        home_flag=None, away_flag=None,
        kickoff_utc=datetime(2026, 6, 28, 16, 0, tzinfo=timezone.utc),
        stage="Group A", status="scheduled",
    )
    bad = ProviderMatch(
        external_id="801", home_team="C", away_team="D",
        home_flag=None, away_flag=None,
        kickoff_utc=BadKickoff(),  # type: ignore[arg-type]
        stage="Group A", status="scheduled",
    )

    # El bad puede caer fuera del rango por fecha; lo metemos a hoy forzando
    # que _kickoff_to_es_date falle dentro del try → se saltea.
    provider = FakeProvider(fixtures=[good, bad])
    result = await sync_fixtures(provider, db_session, today=today, force=True)

    # El bueno entró aunque el malo (si fue relevante) se haya salteado.
    with db_session() as s:
        assert s.query(Match).filter_by(external_id="800").count() == 1


def _provider_match(ext_id, status, day=date(2026, 6, 28)):
    return ProviderMatch(
        external_id=ext_id, home_team="A", away_team="B",
        home_flag=None, away_flag=None,
        kickoff_utc=datetime(day.year, day.month, day.day, 16, 0, tzinfo=timezone.utc),
        stage="Round of 32", status=status,
    )


async def test_sync_does_not_finish_existing_match(db_session):
    """sync NUNCA debe marcar FINISHED (eso es de poll_results, con goles)."""
    today = date(2026, 6, 28)
    with db_session() as s:
        s.add(Match(external_id="900", home="A", away="B",
                    status=MatchStatus.SCHEDULED,
                    kickoff_utc=datetime(2026, 6, 28, 16, 0),
                    match_date_local=today))
        s.commit()

    provider = FakeProvider(fixtures=[_provider_match("900", "finished")])
    await sync_fixtures(provider, db_session, today=today, force=True)

    with db_session() as s:
        m = s.query(Match).filter_by(external_id="900").one()
        assert m.status == MatchStatus.SCHEDULED  # NO finished
        assert m.goals_home is None


async def test_sync_inserts_finished_fixture_as_scheduled(db_session):
    """Un fixture nuevo que ya viene finished se inserta SCHEDULED, no zombi."""
    today = date(2026, 6, 28)
    provider = FakeProvider(fixtures=[_provider_match("901", "finished")])
    await sync_fixtures(provider, db_session, today=today, force=True)

    with db_session() as s:
        m = s.query(Match).filter_by(external_id="901").one()
        assert m.status == MatchStatus.SCHEDULED
        assert m.goals_home is None


async def test_sync_does_not_unfinish_a_closed_match(db_session):
    """Un partido ya FINISHED (con goles) no se degrada desde sync."""
    today = date(2026, 6, 28)
    with db_session() as s:
        s.add(Match(external_id="902", home="A", away="B",
                    status=MatchStatus.FINISHED, goals_home=2, goals_away=1,
                    kickoff_utc=datetime(2026, 6, 28, 16, 0),
                    match_date_local=today))
        s.commit()

    provider = FakeProvider(fixtures=[_provider_match("902", "scheduled")])
    await sync_fixtures(provider, db_session, today=today, force=True)

    with db_session() as s:
        m = s.query(Match).filter_by(external_id="902").one()
        assert m.status == MatchStatus.FINISHED
        assert (m.goals_home, m.goals_away) == (2, 1)


def test_provider_status_map_cancelled_and_postponed():
    from provider.api_football import STATUS_MAP
    assert STATUS_MAP["FT"] == "finished"
    assert STATUS_MAP["PST"] == "scheduled"   # postponed sigue programado
    assert STATUS_MAP["CANC"] == "cancelled"
    assert STATUS_MAP["ABD"] == "cancelled"
    assert STATUS_MAP["AWD"] == "cancelled"
    assert STATUS_MAP["WO"] == "cancelled"
