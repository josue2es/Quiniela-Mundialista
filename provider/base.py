"""Protocolo MatchProvider — contrato tipado sin lógica de red."""

from datetime import date
from typing import Protocol

from provider.models import ProviderMatch, ProviderResult


class MatchProvider(Protocol):
    """Interfaz que todo proveedor de datos debe implementar.

    Desacopla la fuente externa de la lógica de negocio (scoring,
    scheduler, UI).  Permite cambiar de API-Football a BALLDONTLIE
    o scraping sin tocar el resto de la app.
    """

    async def fetch_fixtures(
        self, since: date, until: date
    ) -> list[ProviderMatch]:
        """Obtiene partidos en el rango de fechas UTC [since, until]."""
        ...

    async def fetch_results(
        self, external_ids: list[str]
    ) -> list[ProviderResult]:
        """Obtiene resultados para los partidos con los external_ids dados."""
        ...
