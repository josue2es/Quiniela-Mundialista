"""BalldontlieProvider — fallback de MatchProvider usando BALLDONTLIE FIFA API.

GET https://api.balldontlie.io/fifa/worldcup/v1/matches?seasons[]=2026
Header: Authorization: <api_key>
Paginación por cursor (meta.next_cursor).
home_team/away_team = null para partidos TBD → usar home_team_source.description.
"""

from __future__ import annotations

import logging
import os
from datetime import date, datetime, timezone

import httpx

from provider.models import ProviderMatch, ProviderResult

logger = logging.getLogger(__name__)

BALLDONTLIE_BASE = "https://api.balldontlie.io/fifa/worldcup/v1"
BALLDONTLIE_DEFAULT_SEASON = 2026


def _parse_dt(dt_str: str) -> datetime:
    """Parse ISO 8601 datetime string from Balldontlie → UTC datetime."""
    dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _team_name(team: dict | None, source: dict | None) -> str | None:
    """Extrae el nombre del equipo; usa `source.description` si team es None (TBD)."""
    if team:
        return team.get("name")
    if source:
        return source.get("description") or source.get("placeholder")
    return None


def _flag(team: dict | None) -> str | None:
    """URL de bandera: usamos country_code como fallback (ej. 'ESP')."""
    if team and team.get("country_code"):
        return team["country_code"]
    return None


def _stage_name(match: dict) -> str:
    """Arma el nombre del stage: 'Group A', 'Round of 32', etc."""
    stage = match.get("stage", {}) or {}
    group = match.get("group") or {}
    if group:
        return group.get("name", stage.get("name", "Unknown"))
    return stage.get("name", "Unknown")


STATUS_MAP = {
    "scheduled": "scheduled",
    "in_progress": "live",
    "completed": "finished",
    "postponed": "scheduled",
    "cancelled": "finished",
}


def _map_status(bd_status: str) -> str:
    return STATUS_MAP.get(bd_status, "scheduled")


class BalldontlieProvider:
    """Implementación de MatchProvider usando la API Balldontlie FIFA.

    Baja prioridad — usar solo como fallback si API-Football falla
    o se agota el rate limit.

    Parameters
    ----------
    api_key: str
        API key de Balldontlie (sign up en https://app.balldontlie.io).
        Si es None, se lee de BALLDONTLIE_API_KEY.
    """

    def __init__(self, api_key: str | None = None) -> None:
        self._api_key = api_key or os.environ.get("BALLDONTLIE_API_KEY", "")
        if not self._api_key:
            logger.warning(
                "BalldontlieProvider: BALLDONTLIE_API_KEY no configurada "
                "— las llamadas a la API fallarán con 401."
            )
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=BALLDONTLIE_BASE,
                headers={"Authorization": self._api_key},
                timeout=httpx.Timeout(30.0),
            )
        return self._client

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    # ── fetch_fixtures ────────────────────────────────────────────────────

    async def fetch_fixtures(
        self, since: date, until: date
    ) -> list[ProviderMatch]:
        """Obtiene partidos en el rango [since, until] usando paginación por cursor.

        La API de Balldontlie no filtra por fecha, así que descargamos todos
        los partidos de la temporada 2026 y filtramos localmente (104 partidos
        máximo — overhead aceptable).
        """
        client = await self._get_client()
        all_matches: list[dict] = []
        params: dict = {"seasons[]": BALLDONTLIE_DEFAULT_SEASON, "per_page": 100}
        pages = 0

        while True:
            pages += 1
            logger.debug("Balldontlie fetch_fixtures page %d", pages)
            resp = await client.get("/matches", params=params)
            resp.raise_for_status()
            body = resp.json()
            data = body.get("data", [])
            all_matches.extend(data)

            meta = body.get("meta", {})
            next_cursor = meta.get("next_cursor")
            if not next_cursor:
                break
            params["cursor"] = next_cursor

        since_dt = datetime.combine(since, datetime.min.time(), tzinfo=timezone.utc)
        until_dt = datetime.combine(until, datetime.max.time(), tzinfo=timezone.utc)

        fixtures: list[ProviderMatch] = []
        for m in all_matches:
            dt_str = m.get("datetime")
            if not dt_str:
                continue
            kickoff = _parse_dt(dt_str)
            if not (since_dt <= kickoff <= until_dt):
                continue

            fixtures.append(
                ProviderMatch(
                    external_id=str(m["id"]),
                    home_team=_team_name(m.get("home_team"), m.get("home_team_source")),
                    away_team=_team_name(m.get("away_team"), m.get("away_team_source")),
                    home_flag=_flag(m.get("home_team")),
                    away_flag=_flag(m.get("away_team")),
                    kickoff_utc=kickoff,
                    stage=_stage_name(m),
                    status=_map_status(m.get("status", "scheduled")),
                )
            )

        logger.info(
            "Balldontlie fetch_fixtures: %d matches en %d páginas, "
            "%d en rango [%s, %s]",
            len(all_matches), pages, len(fixtures), since, until,
        )
        return fixtures

    # ── fetch_results ─────────────────────────────────────────────────────

    async def fetch_results(
        self, external_ids: list[str]
    ) -> list[ProviderResult]:
        """Obtiene resultados para los external_ids dados.

        Usa match_ids[] para filtrar en la API y evitar descargar todo.
        """
        if not external_ids:
            return []

        client = await self._get_client()
        int_ids = [int(x) for x in external_ids]

        # Balldontlie acepta múltiples match_ids[] en query string
        params: dict = {
            "match_ids[]": int_ids,
            "per_page": 100,
        }

        results: list[ProviderResult] = []
        pages = 0

        while True:
            pages += 1
            logger.debug("Balldontlie fetch_results page %d (ids=%s)", pages, int_ids)
            resp = await client.get("/matches", params=params)
            resp.raise_for_status()
            body = resp.json()
            data = body.get("data", [])

            for m in data:
                home_goals = m.get("home_score")
                away_goals = m.get("away_score")
                status = _map_status(m.get("status", "scheduled"))

                # Solo incluimos si hay datos de resultado (goles o status finished)
                if home_goals is None and away_goals is None:
                    if status != "finished":
                        continue
                    home_goals = 0
                    away_goals = 0

                results.append(
                    ProviderResult(
                        external_id=str(m["id"]),
                        home_goals=home_goals or 0,
                        away_goals=away_goals or 0,
                        status=status,
                    )
                )

            meta = body.get("meta", {})
            next_cursor = meta.get("next_cursor")
            if not next_cursor:
                break
            params["cursor"] = next_cursor

        logger.info(
            "Balldontlie fetch_results: %d results para %d IDs en %d páginas",
            len(results), len(external_ids), pages,
        )
        return results
