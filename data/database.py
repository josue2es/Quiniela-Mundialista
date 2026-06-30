"""Database engine, session factory, WAL mode, and player seed from CSV.

§4 + §8: SQLite WAL, seed_players (upsert by name), init_db.
Imports the authoritative models from data.models.
"""

import csv
import os
from collections.abc import Generator
from contextlib import contextmanager

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from data.models import Base, Player

DB_PATH = os.environ.get("DB_PATH", os.path.join(os.path.dirname(__file__), "..", "quiniela.db"))
CSV_PATH = os.environ.get("PLAYERS_CSV", os.path.join(os.path.dirname(__file__), "..", "players.csv"))

engine = create_engine(
    f"sqlite:///{DB_PATH}",
    connect_args={"check_same_thread": False},
    echo=False,
)


@event.listens_for(engine, "connect")
def _set_wal(dbapi_connection, _connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL;")
    cursor.execute("PRAGMA foreign_keys=ON;")
    cursor.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def get_session() -> Generator[Session, None, None]:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@contextmanager
def session_scope() -> Generator[Session, None, None]:
    """Transactional scope: commits on success, rolls back on error, always closes."""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def init_db(drop_all: bool = False):
    """Create all tables (and optionally drop them first).

    Args:
        drop_all: If True, drops every table before recreating (destructive).
    """
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    if drop_all:
        Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    _migrate_add_columns()


def _migrate_add_columns():
    """Lightweight migrations for SQLite (no Alembic).

    Adds columns introduced after a DB was first created, so existing
    deployments don't need to drop their data. Idempotent.
    """
    with engine.begin() as conn:
        existing = {
            row[1]
            for row in conn.exec_driver_sql("PRAGMA table_info(players)").fetchall()
        }
        if "initial_points" not in existing:
            conn.exec_driver_sql(
                "ALTER TABLE players ADD COLUMN initial_points INTEGER NOT NULL DEFAULT 0"
            )
        if "is_admin" not in existing:
            conn.exec_driver_sql(
                "ALTER TABLE players ADD COLUMN is_admin BOOLEAN NOT NULL DEFAULT 0"
            )

        match_cols = {
            row[1]
            for row in conn.exec_driver_sql("PRAGMA table_info(matches)").fetchall()
        }
        if "pen_home" not in match_cols:
            conn.exec_driver_sql("ALTER TABLE matches ADD COLUMN pen_home INTEGER")
        if "pen_away" not in match_cols:
            conn.exec_driver_sql("ALTER TABLE matches ADD COLUMN pen_away INTEGER")


def _parse_int(value: str, default: int = 0) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def _parse_bool(value: str) -> bool:
    return str(value).strip().lower() in ("true", "1", "yes")


def seed_players(csv_path: str | None = None):
    """Upsert players from CSV (idempotent — re-running won't duplicate).

    CSV columns: name,password[,initial_points][,is_admin]
    - password: updated only if it changed.
    - initial_points: optional handicap added to the player's total; updated
      whenever present in the CSV. Defaults to 0 when the column is absent.
    - is_admin: optional; truthy ("true"/"1"/"yes") grants admin. Updated
      whenever present in the CSV. Defaults to False when the column is absent.
    Never touches avatar_flag or is_setup on existing players.
    New players get defaults: is_setup=False, avatar_flag=🏴.
    """
    path = csv_path or CSV_PATH
    # isfile (not exists): si el bind-mount de Docker crea un directorio falso
    # cuando players.csv no existe en el host, no intentamos abrirlo como archivo.
    if not os.path.isfile(path):
        return

    with SessionLocal() as session:
        with open(path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            fields = reader.fieldnames or []
            has_initial = "initial_points" in fields
            has_admin = "is_admin" in fields
            for row in reader:
                name = row.get("name", "").strip()
                password = row.get("password", "").strip()
                if not name:
                    continue
                initial = _parse_int(row.get("initial_points", 0)) if has_initial else None
                admin = _parse_bool(row.get("is_admin", "")) if has_admin else None
                existing = session.query(Player).filter_by(name=name).first()
                if existing:
                    if password and existing.password != password:
                        existing.password = password
                    if initial is not None and existing.initial_points != initial:
                        existing.initial_points = initial
                    if admin is not None and existing.is_admin != admin:
                        existing.is_admin = admin
                else:
                    session.add(
                        Player(
                            name=name,
                            password=password,
                            initial_points=initial or 0,
                            is_admin=admin or False,
                        )
                    )
        session.commit()
