"""Bloqueo de login por intentos fallidos + utilidades para el admin.

Política: tras MAX_FAILED_ATTEMPTS contraseñas incorrectas seguidas, la cuenta
queda bloqueada LOCKOUT_MINUTES. Durante el bloqueo no se valida la contraseña.
El admin puede desbloquear desde su panel.

Las marcas de tiempo se guardan en UTC naive (datetime.utcnow), igual que el
resto de columnas DateTime del proyecto, para evitar líos naive/aware con SQLite.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Callable, Optional

from sqlalchemy.orm import Session

from data.database import SessionLocal
from data.models import Player

MAX_FAILED_ATTEMPTS = 5
LOCKOUT_MINUTES = 60


def is_locked(player: Player, *, now: Optional[datetime] = None) -> bool:
    """True si la cuenta está bloqueada en este momento."""
    now = now or datetime.utcnow()
    return player.locked_until is not None and player.locked_until > now


def lock_remaining_minutes(player: Player, *, now: Optional[datetime] = None) -> int:
    """Minutos restantes de bloqueo (redondeado hacia arriba, mín. 1)."""
    now = now or datetime.utcnow()
    if player.locked_until is None or player.locked_until <= now:
        return 0
    secs = (player.locked_until - now).total_seconds()
    return max(1, int((secs + 59) // 60))


def remaining_attempts(player: Player) -> int:
    """Intentos que le quedan antes del bloqueo."""
    return max(0, MAX_FAILED_ATTEMPTS - (player.failed_attempts or 0))


def register_failure(
    session: Session, player: Player, *, now: Optional[datetime] = None
) -> bool:
    """Suma un intento fallido y bloquea si llega al umbral.

    Devuelve True si la cuenta quedó bloqueada por este fallo. NO hace commit:
    el llamante decide cuándo persistir.
    """
    now = now or datetime.utcnow()
    player.failed_attempts = (player.failed_attempts or 0) + 1
    if player.failed_attempts >= MAX_FAILED_ATTEMPTS:
        player.locked_until = now + timedelta(minutes=LOCKOUT_MINUTES)
        player.failed_attempts = 0  # el candado pasa a ser la barrera
        return True
    return False


def register_success(player: Player) -> None:
    """Limpia el estado de bloqueo tras un login correcto. NO hace commit."""
    player.failed_attempts = 0
    player.locked_until = None


def locked_players(
    session_factory: Callable[[], Session] = SessionLocal,
) -> list[dict]:
    """Jugadores actualmente bloqueados (para el panel de admin)."""
    now = datetime.utcnow()
    with session_factory() as session:
        players = (
            session.query(Player)
            .filter(Player.locked_until.isnot(None), Player.locked_until > now)
            .order_by(Player.name)
            .all()
        )
        return [
            {
                "id": p.id,
                "name": p.name,
                "avatar_flag": p.avatar_flag,
                "locked_until": p.locked_until,
            }
            for p in players
        ]


def unlock_player(
    player_id: int, session_factory: Callable[[], Session] = SessionLocal
) -> bool:
    """Desbloquea una cuenta (acción de admin).

    Devuelve True si el jugador existía y se limpió su bloqueo.
    """
    with session_factory() as session:
        player = session.get(Player, player_id)
        if player is None:
            return False
        player.failed_attempts = 0
        player.locked_until = None
        session.commit()
        return True
