"""Bloqueo de login por intentos fallidos, POR DIRECCIÓN IP.

Política: tras MAX_FAILED_ATTEMPTS contraseñas incorrectas seguidas desde una
misma IP, esa IP queda bloqueada LOCKOUT_MINUTES. Durante el bloqueo no se
valida la contraseña. El admin puede desbloquear una IP desde su panel.

Las marcas de tiempo se guardan en UTC naive (datetime.utcnow), igual que el
resto de columnas DateTime del proyecto, para evitar líos naive/aware con SQLite.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Callable, Optional

from sqlalchemy.orm import Session

from data.database import SessionLocal
from data.models import LoginAttempt

MAX_FAILED_ATTEMPTS = 5
LOCKOUT_MINUTES = 60


def _get(session: Session, ip: str) -> Optional[LoginAttempt]:
    return session.query(LoginAttempt).filter_by(ip=ip).first()


def _get_or_create(session: Session, ip: str) -> LoginAttempt:
    row = _get(session, ip)
    if row is None:
        row = LoginAttempt(ip=ip, failed_attempts=0)
        session.add(row)
        session.flush()
    return row


def is_locked(session: Session, ip: str, *, now: Optional[datetime] = None) -> bool:
    """True si la IP está bloqueada en este momento."""
    now = now or datetime.utcnow()
    row = _get(session, ip)
    return row is not None and row.locked_until is not None and row.locked_until > now


def lock_remaining_minutes(
    session: Session, ip: str, *, now: Optional[datetime] = None
) -> int:
    """Minutos restantes de bloqueo para la IP (redondeado hacia arriba, mín. 1)."""
    now = now or datetime.utcnow()
    row = _get(session, ip)
    if row is None or row.locked_until is None or row.locked_until <= now:
        return 0
    secs = (row.locked_until - now).total_seconds()
    return max(1, int((secs + 59) // 60))


def remaining_attempts(session: Session, ip: str) -> int:
    """Intentos que le quedan a la IP antes del bloqueo."""
    row = _get(session, ip)
    used = row.failed_attempts if row else 0
    return max(0, MAX_FAILED_ATTEMPTS - used)


def register_failure(
    session: Session, ip: str, *, now: Optional[datetime] = None
) -> bool:
    """Suma un intento fallido para la IP y la bloquea si llega al umbral.

    Devuelve True si la IP quedó bloqueada por este fallo. NO hace commit:
    el llamante decide cuándo persistir.
    """
    now = now or datetime.utcnow()
    row = _get_or_create(session, ip)
    row.failed_attempts = (row.failed_attempts or 0) + 1
    row.updated_at = now
    if row.failed_attempts >= MAX_FAILED_ATTEMPTS:
        row.locked_until = now + timedelta(minutes=LOCKOUT_MINUTES)
        row.failed_attempts = 0  # el candado pasa a ser la barrera
        return True
    return False


def register_success(session: Session, ip: str) -> None:
    """Limpia el estado de bloqueo de la IP tras un login correcto. NO commitea."""
    row = _get(session, ip)
    if row is not None:
        row.failed_attempts = 0
        row.locked_until = None
        row.updated_at = datetime.utcnow()


def locked_ips(
    session_factory: Callable[[], Session] = SessionLocal,
) -> list[dict]:
    """IPs actualmente bloqueadas (para el panel de admin)."""
    now = datetime.utcnow()
    with session_factory() as session:
        rows = (
            session.query(LoginAttempt)
            .filter(
                LoginAttempt.locked_until.isnot(None),
                LoginAttempt.locked_until > now,
            )
            .order_by(LoginAttempt.locked_until)
            .all()
        )
        return [
            {"ip": r.ip, "locked_until": r.locked_until}
            for r in rows
        ]


def unlock_ip(
    ip: str, session_factory: Callable[[], Session] = SessionLocal
) -> bool:
    """Desbloquea una IP (acción de admin).

    Devuelve True si existía un registro y se limpió su bloqueo.
    """
    with session_factory() as session:
        row = _get(session, ip)
        if row is None:
            return False
        row.failed_attempts = 0
        row.locked_until = None
        row.updated_at = datetime.utcnow()
        session.commit()
        return True
