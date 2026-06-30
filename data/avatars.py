"""Almacenamiento y URLs de los avatares (.webp) de los jugadores.

El admin sube un sticker .webp por jugador. Se guarda en AVATARS_DIR (dentro
del volumen de datos, persistente) y se sirve bajo AVATARS_URL_PREFIX. La URL
incluye un ?v=<timestamp> para romper el caché del navegador al reemplazarlo.
"""

from __future__ import annotations

import os
import time

from data.database import DB_PATH

# Por defecto, junto a la BD (mismo volumen persistente, p.ej. /data/avatars).
AVATARS_DIR = os.environ.get(
    "AVATARS_DIR",
    os.path.join(os.path.dirname(os.path.abspath(DB_PATH)), "avatars"),
)
AVATARS_URL_PREFIX = "/avatars"


def ensure_dir() -> str:
    """Crea el directorio de avatares si no existe y devuelve su ruta."""
    os.makedirs(AVATARS_DIR, exist_ok=True)
    return AVATARS_DIR


def is_webp(data: bytes) -> bool:
    """True si los bytes son un WebP válido (cabecera RIFF....WEBP)."""
    return len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP"


def save_avatar(player_id: int, data: bytes) -> str:
    """Guarda el .webp del jugador y devuelve la URL servida (con cache-bust).

    Lanza ValueError si el contenido no es un WebP válido.
    """
    if not is_webp(data):
        raise ValueError("El archivo no es un .webp válido (sticker de WhatsApp).")
    ensure_dir()
    path = os.path.join(AVATARS_DIR, f"{player_id}.webp")
    with open(path, "wb") as f:
        f.write(data)
    return f"{AVATARS_URL_PREFIX}/{player_id}.webp?v={int(time.time())}"
