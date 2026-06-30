"""ApiFootballProvider — implementación de MatchProvider contra api-football v3.

Usa httpx async. Normaliza la respuesta JSON a ProviderMatch / ProviderResult.
Rate limit: ~100 req/día con contador local reseteado a medianoche UTC.
"""

from __future__ import annotations

import asyncio
import os
import time
from datetime import date, datetime, timezone
from typing import Any

import httpx

from provider.base import MatchProvider
from provider.models import ProviderMatch, ProviderResult

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

API_BASE = "https://v3.football.api-sports.io"
API_KEY = os.environ.get("APIFOOTBALL_KEY", "")
DEFAULT_LEAGUE = 1          # World Cup
DEFAULT_SEASON = 2026

# Mapeo de status.short → status normalizado
STATUS_MAP: dict[str, str] = {
    "NS":  "scheduled",
    "TBD": "scheduled",
    "1H":  "live",
    "HT":  "live",
    "2H":  "live",
    "ET":  "live",
    "BT":  "live",   # break time (extra time half)
    "P":   "live",   # penalty in progress
    "SUSP": "live",  # suspended
    "INT":  "live",  # interrupted
    "FT":  "finished",
    "AET": "finished",
    "PEN": "finished",
    "PST":  "scheduled",  # postponed → sigue programado (se jugará más tarde)
    "CANC": "cancelled",  # cancelled
    "ABD":  "cancelled",  # abandoned
    "AWD":  "cancelled",  # technical loss (awarded)
    "WO":   "cancelled",  # walkover
}


# ---------------------------------------------------------------------------
# Rate limiter (simple, single-instance, reset a medianoche UTC)
# ---------------------------------------------------------------------------

class _RateLimiter:
    """Contador local de requests diario. No thread-safe — uso en asyncio."""

    def __init__(self, max_per_day: int = 100) -> None:
        self._max = max_per_day
        self._count = 0
        self._day: int | None = None

    def _reset_if_new_day(self) -> None:
        today = date.today().toordinal()
        if self._day != today:
            self._day = today
            self._count = 0

    async def acquire(self) -> None:
        self._reset_if_new_day()
        while self._count >= self._max:
            # Espera 60 s y vuelve a mirar — el día podría haber cambiado
            await asyncio.sleep(60)
            self._reset_if_new_day()
        self._count += 1

    @property
    def remaining(self) -> int:
        self._reset_if_new_day()
        return max(0, self._max - self._count)


# ---------------------------------------------------------------------------
# Provider
# ---------------------------------------------------------------------------

class ApiFootballProvider:
    """Implementación de MatchProvider contra api-football.com (v3).

    Uso:
        async with ApiFootballProvider() as provider:
            matches = await provider.fetch_fixtures(since, until)
            results = await provider.fetch_results(ids)
    """

    def __init__(
        self,
        api_key: str | None = None,
        league: int = DEFAULT_LEAGUE,
        season: int = DEFAULT_SEASON,
    ) -> None:
        self._api_key = api_key or API_KEY
        if not self._api_key:
            raise ValueError(
                "APIFOOTBALL_KEY no configurada. Pásala como api_key= "
                "o define la variable de entorno APIFOOTBALL_KEY."
            )
        self._league = league
        self._season = season
        self._limiter = _RateLimiter(max_per_day=100)
        self._client: httpx.AsyncClient | None = None

    # Context manager --------------------------------------------------------

    async def __aenter__(self) -> "ApiFootballProvider":
        self._client = httpx.AsyncClient(
            base_url=API_BASE,
            headers={
                "x-apisports-key": self._api_key,
                "Accept": "application/json",
            },
            timeout=30,
        )
        return self

    async def __aexit__(self, *args: Any) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    # MatchProvider ----------------------------------------------------------

    async def fetch_fixtures(
        self, since: date, until: date
    ) -> list[ProviderMatch]:
        """Trae fixtures en [since, until] desde GET /fixtures iterando por día."""
        if not self._client:
            raise RuntimeError("Usa 'async with ApiFootballProvider() as p:'")

        all_matches: list[ProviderMatch] = []

        # API-Football no soporta rangos — iteramos día a día
        current = since
        while current <= until:
            day_matches = await self._fetch_day(current)
            all_matches.extend(day_matches)
            # Avanza al día siguiente
            current = date.fromordinal(current.toordinal() + 1)

        return all_matches

    async def fetch_results(
        self, external_ids: list[str]
    ) -> list[ProviderResult]:
        """Obtiene resultados para partidos específicos.

        La API de fixtures ya devuelve goals cuando el partido terminó,
        así que buscamos fixture por fixture.
        """
        if not self._client:
            raise RuntimeError("Usa 'async with ApiFootballProvider() as p:'")

        results: list[ProviderResult] = []

        for ext_id in external_ids:
            match = await self._fetch_fixture_by_id(ext_id)
            if match:
                result = self._to_result(match)
                if result:
                    results.append(result)

        return results

    # Internals --------------------------------------------------------------

    async def _fetch_day(self, day: date) -> list[ProviderMatch]:
        """GET /fixtures?league=&season=&date=YYYY-MM-DD"""
        await self._limiter.acquire()

        assert self._client is not None
        resp = await self._client.get(
            "/fixtures",
            params={
                "league": str(self._league),
                "season": str(self._season),
                "date": day.isoformat(),
            },
        )
        resp.raise_for_status()
        data = resp.json()

        # api-football devuelve {"get": "...", "parameters": {...}, "errors": [...], "results": N, "response": [...]}
        fixtures: list[dict[str, Any]] = data.get("response", [])
        return [self._normalize_match(f) for f in fixtures]

    async def _fetch_fixture_by_id(self, fixture_id: str) -> dict[str, Any] | None:
        """GET /fixtures?id=<fixture_id>"""
        await self._limiter.acquire()

        assert self._client is not None
        resp = await self._client.get(
            "/fixtures",
            params={"id": fixture_id},
        )
        resp.raise_for_status()
        data = resp.json()
        fixtures: list[dict[str, Any]] = data.get("response", [])
        return fixtures[0] if fixtures else None

    def _normalize_match(self, raw: dict[str, Any]) -> ProviderMatch:
        """Convierte un fixture de API-Football en ProviderMatch."""
        fixture = raw.get("fixture", {})
        league = raw.get("league", {})
        teams = raw.get("teams", {})

        # fixture.id -> external_id (como string)
        external_id = str(fixture.get("id", ""))

        # fixture.date -> kickoff_utc (ISO 8601 con TZ, ej. "2026-06-11T16:00:00+00:00")
        kickoff_str = fixture.get("date", "")
        kickoff_utc = _parse_utc(kickoff_str)

        # fixture.status.short -> status normalizado
        raw_status = fixture.get("status", {}).get("short", "NS")
        status = STATUS_MAP.get(raw_status, "scheduled")

        # teams.home/away
        home = teams.get("home", {})
        away = teams.get("away", {})

        home_team: str | None = home.get("name") or None
        away_team: str | None = away.get("name") or None
        home_flag: str | None = home.get("logo") or None
        away_flag: str | None = away.get("logo") or None

        # league.round -> stage
        stage = league.get("round", "")

        # Si no hay round, usar la fecha como fallback
        if not stage:
            stage = kickoff_str[:10] if kickoff_str else "TBD"

        return ProviderMatch(
            external_id=external_id,
            home_team=home_team,
            away_team=away_team,
            home_flag=home_flag,
            away_flag=away_flag,
            kickoff_utc=kickoff_utc,
            stage=stage,
            status=status,
        )

    @staticmethod
    def _to_result(raw: dict[str, Any]) -> ProviderResult | None:
        """Convierte un fixture de API-Football en ProviderResult si tiene goles."""
        fixture = raw.get("fixture", {})
        goals = raw.get("goals", {})

        external_id = str(fixture.get("id", ""))
        home_goals = goals.get("home")
        away_goals = goals.get("away")

        # Solo devolvemos resultado si hay goles registrados (None sin jugar)
        if home_goals is None or away_goals is None:
            return None

        raw_status = fixture.get("status", {}).get("short", "NS")
        status = STATUS_MAP.get(raw_status, "scheduled")

        # Tanda de penales: score.penalty trae los goles del shootout cuando el
        # partido se decidió por penales (status PEN). goals.* sigue siendo el
        # marcador reglamentario/prórroga (empate). None si no hubo penales.
        penalty = raw.get("score", {}).get("penalty", {}) or {}
        pen_home = penalty.get("home")
        pen_away = penalty.get("away")

        return ProviderResult(
            external_id=external_id,
            home_goals=int(home_goals),
            away_goals=int(away_goals),
            status=status,
            pen_home=int(pen_home) if pen_home is not None else None,
            pen_away=int(pen_away) if pen_away is not None else None,
        )

    # Utility ----------------------------------------------------------------

    @property
    def remaining_today(self) -> int:
        """Requests restantes hoy."""
        return self._limiter.remaining


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_utc(iso_str: str) -> datetime:
    """Parsea una fecha ISO 8601 con o sin zona horaria a datetime UTC-aware."""
    if not iso_str:
        return datetime.now(timezone.utc)

    # Caso típico: "2026-06-11T16:00:00+00:00"
    try:
        dt = datetime.fromisoformat(iso_str)
    except ValueError:
        # Intenta sin zona: "2026-06-11T16:00:00"
        try:
            dt = datetime.fromisoformat(iso_str).replace(tzinfo=timezone.utc)
        except ValueError:
            return datetime.now(timezone.utc)

    # Asegurar UTC
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt
