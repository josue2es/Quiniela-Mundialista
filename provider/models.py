"""DTOs normalizados para el MatchProvider. Todo en UTC."""

from dataclasses import dataclass
from datetime import datetime


@dataclass
class ProviderMatch:
    """Partido normalizado desde una fuente externa.

    Campos con None indican información aún no disponible (ej. equipos TBD).
    """

    external_id: str
    home_team: str | None  # None = TBD
    away_team: str | None  # None = TBD
    home_flag: str | None  # URL o código ISO
    away_flag: str | None  # URL o código ISO
    kickoff_utc: datetime
    stage: str  # "Group A", "Round of 32", ...
    status: str  # "scheduled" | "live" | "finished"


@dataclass
class ProviderResult:
    """Resultado de un partido desde una fuente externa."""

    external_id: str
    home_goals: int
    away_goals: int
    status: str  # "finished" cuando aplica
