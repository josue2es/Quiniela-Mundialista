"""Database engine, session factory, WAL mode, and player seed from CSV.

§4 + §8: SQLite WAL, seed_players (upsert by name), init_db.
Imports the authoritative models from data.models.
"""

import csv
import os
from collections.abc import Generator

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


def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    Base.metadata.create_all(bind=engine)


def seed_players(csv_path: str | None = None):
    """Upsert players from CSV (idempotent — re-running won't duplicate).

    CSV columns: name,password
    Only updates password if changed; never touches avatar_flag or is_setup.
    New players get defaults: is_setup=False, avatar_flag=🏴.
    """
    path = csv_path or CSV_PATH
    if not os.path.exists(path):
        return

    with SessionLocal() as session:
        with open(path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                name = row.get("name", "").strip()
                password = row.get("password", "").strip()
                if not name:
                    continue
                existing = session.query(Player).filter_by(name=name).first()
                if existing:
                    if password and existing.password != password:
                        existing.password = password
                else:
                    session.add(Player(name=name, password=password))
        session.commit()
