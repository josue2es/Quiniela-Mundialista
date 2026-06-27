"""sync_fixtures — job del scheduler que pobla/actualiza la tabla matches.

CA: pobla/actualiza matches vía MatchProvider. Resuelve TBD del día siguiente.
Convierte kickoff_utc → match_date_local (America/El_Salvador, UTC-6).
Cachea fixtures para respetar rate limit del proveedor.

§6: La API usa fechas UTC; el rango UTC debe cubrir el día ES completo.
§7: Se corre varias veces/día + al terminar el último partido del día.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Callable
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from data.models import Match, MatchStatus
from provider import MatchProvider

logger = logging.getLogger(__name__)

# ── Timezone constants ─────────────────────────────────────────────────────
ES_TZ = ZoneInfo("America/El_Salvador")   # UTC-6 fijo, sin DST
UTC = timezone.utc

# ── Status mapping: ProviderMatch.status → MatchStatus enum ─────────────────
_STATUS_MAP: dict[str, MatchStatus] = {
    "scheduled": MatchStatus.SCHEDULED,
    "live": MatchStatus.LIVE,
    "finished": MatchStatus.FINISHED,
    "cancelled": MatchStatus.CANCELLED,
}


def _map_status(status_str: str) -> MatchStatus:
    return _STATUS_MAP.get(status_str, MatchStatus.SCHEDULED)


# ── Date helpers ──────────────────────────────────────────────────────────

def es_today() -> date:
    """Today's date in El Salvador (UTC-6)."""
    return datetime.now(ES_TZ).date()


def _utc_range_for_es_day(es_day: date) -> tuple[datetime, datetime]:
    """Convert an ES calendar day to the UTC range that fully covers it.

    ES day runs from 00:00 to 24:00 ES (UTC-6), which is 06:00 UTC same
    calendar day to 06:00 UTC next calendar day.

    Returns (start_utc, end_utc) where end_utc is exclusive.
    """
    start_es = datetime.combine(es_day, datetime.min.time(), tzinfo=ES_TZ)
    end_es = start_es + timedelta(days=1)
    return start_es.astimezone(UTC), end_es.astimezone(UTC)


def _kickoff_to_es_date(kickoff_utc: datetime) -> date:
    """Convert a UTC kickoff to the ES local date (match_date_local)."""
    if kickoff_utc.tzinfo is None:
        kickoff_utc = kickoff_utc.replace(tzinfo=UTC)
    return kickoff_utc.astimezone(ES_TZ).date()


# ── Simple TTL cache for fixture results ──────────────────────────────────

class _FixtureCache:
    """In-memory cache with TTL to avoid re-fetching on every scheduler tick.

    Strategy (§7): fixtures change rarely — cache until next day or until
    a force-refresh (e.g. after last match of the day finishes).
    """

    def __init__(self, ttl_seconds: int = 3600) -> None:
        self._ttl = ttl_seconds
        self._data: dict[str, tuple[float, list]] = {}  # key → (expiry, fixtures)

    def get(self, key: str) -> list | None:
        entry = self._data.get(key)
        if entry is None:
            return None
        expiry, fixtures = entry
        if datetime.now(UTC).timestamp() > expiry:
            del self._data[key]
            return None
        return fixtures

    def set(self, key: str, fixtures: list) -> None:
        expiry = datetime.now(UTC).timestamp() + self._ttl
        self._data[key] = (expiry, fixtures)

    def clear(self) -> None:
        self._data.clear()


# Shared cache instance (one per process)
_fixture_cache = _FixtureCache(ttl_seconds=3600)


# ── Main sync function ────────────────────────────────────────────────────

async def sync_fixtures(
    provider: MatchProvider,
    session_factory: Callable[[], Session],
    *,
    today: date | None = None,
    force: bool = False,
) -> dict:
    """Sync matches for today and tomorrow (El Salvador local dates).

    Fetches fixtures from the provider (with caching), then upserts into
    the ``matches`` table keyed on ``external_id``.  Matches that were
    previously TBD (null home/away) are updated when the provider
    supplies the teams.

    Parameters
    ----------
    provider : MatchProvider
        Async provider (ApiFootballProvider or fallback).
    session_factory : callable
        Returns a new SQLAlchemy ``Session`` (e.g. ``data.database.SessionLocal``).
    today : date or None
        ES today; computed automatically if ``None``.
    force : bool
        If True, bypass the fixture cache and re-fetch.

    Returns
    -------
    dict
        Counts for observability: ``fixtures_fetched``, ``relevant``,
        ``inserted``, ``updated``, ``tbd_resolved``.
    """
    if today is None:
        today = es_today()
    tomorrow = today + timedelta(days=1)

    # ── Calculate UTC range covering both ES days (§6) ──────────────────
    start_utc, _ = _utc_range_for_es_day(today)
    _, end_utc = _utc_range_for_es_day(tomorrow)

    since_date = start_utc.date()
    until_date = (end_utc - timedelta(seconds=1)).date()

    # ── Fetch (with cache) ───────────────────────────────────────────────
    cache_key = f"{since_date.isoformat()}_{until_date.isoformat()}"
    fixtures_raw = None if force else _fixture_cache.get(cache_key)

    if fixtures_raw is None:
        logger.info(
            "sync_fixtures: fetching %s → %s (UTC) for ES %s + %s",
            since_date, until_date, today, tomorrow,
        )
        fixtures_raw = await provider.fetch_fixtures(since_date, until_date)
        _fixture_cache.set(cache_key, fixtures_raw)
    else:
        logger.info(
            "sync_fixtures: using cached fixtures (%d raw, %s → %s)",
            len(fixtures_raw), since_date, until_date,
        )

    # ── Filter to only today + tomorrow ES matches ──────────────────────
    target_dates = {today, tomorrow}
    relevant: list = []
    for pm in fixtures_raw:
        match_date_es = _kickoff_to_es_date(pm.kickoff_utc)
        if match_date_es in target_dates:
            relevant.append(pm)

    if not relevant:
        logger.info("sync_fixtures: 0 relevant matches for %s / %s", today, tomorrow)
        return {
            "fixtures_fetched": len(fixtures_raw),
            "relevant": 0,
            "inserted": 0,
            "updated": 0,
            "tbd_resolved": 0,
        }

    # ── Upsert into DB ──────────────────────────────────────────────────
    inserted = 0
    updated = 0
    tbd_resolved = 0

    session = session_factory()
    try:
        for pm in relevant:
            match_date_local = _kickoff_to_es_date(pm.kickoff_utc)
            existing = (
                session.query(Match)
                .filter_by(external_id=pm.external_id)
                .first()
            )

            if existing:
                changed = False

                # Resolver TBD (§3: equipos se rellenan cuando el proveedor los da)
                if existing.home is None and pm.home_team is not None:
                    existing.home = pm.home_team
                    changed = True
                    tbd_resolved += 1
                if existing.away is None and pm.away_team is not None:
                    existing.away = pm.away_team
                    changed = True

                # Flags
                if pm.home_flag and existing.home_flag != pm.home_flag:
                    existing.home_flag = pm.home_flag
                    changed = True
                if pm.away_flag and existing.away_flag != pm.away_flag:
                    existing.away_flag = pm.away_flag
                    changed = True

                # Stage
                if pm.stage and existing.stage != pm.stage:
                    existing.stage = pm.stage
                    changed = True

                # Status
                new_status = _map_status(pm.status)
                if existing.status != new_status:
                    existing.status = new_status
                    changed = True

                # Kickoff time
                if (existing.kickoff_utc is None
                        or abs((pm.kickoff_utc - existing.kickoff_utc).total_seconds()) > 60):
                    existing.kickoff_utc = pm.kickoff_utc
                    existing.match_date_local = match_date_local
                    changed = True

                if changed:
                    updated += 1
            else:
                session.add(
                    Match(
                        external_id=pm.external_id,
                        home=pm.home_team,
                        away=pm.away_team,
                        home_flag=pm.home_flag,
                        away_flag=pm.away_flag,
                        kickoff_utc=pm.kickoff_utc,
                        match_date_local=match_date_local,
                        stage=pm.stage,
                        status=_map_status(pm.status),
                    )
                )
                inserted += 1

        session.commit()
        logger.info(
            "sync_fixtures: inserted=%d updated=%d tbd_resolved=%d (of %d relevant)",
            inserted, updated, tbd_resolved, len(relevant),
        )
    except Exception:
        session.rollback()
        logger.exception("sync_fixtures: rollback due to error")
        raise
    finally:
        session.close()

    return {
        "fixtures_fetched": len(fixtures_raw),
        "relevant": len(relevant),
        "inserted": inserted,
        "updated": updated,
        "tbd_resolved": tbd_resolved,
    }
