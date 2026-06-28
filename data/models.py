"""SQLAlchemy 2.0 ORM models for Quiniela Mundialista.

All models use modern declarative style with Mapped[] annotations.
Avoid DetachedInstanceError: always convert to dict before session close.
"""

import enum
from datetime import datetime, date
from typing import Optional

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    Date,
    Enum,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    event,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class MatchStatus(str, enum.Enum):
    SCHEDULED = "scheduled"
    LIVE = "live"
    FINISHED = "finished"
    CANCELLED = "cancelled"


class Player(Base):
    __tablename__ = "players"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    password: Mapped[str] = mapped_column(String(255), nullable=False)  # plain text
    avatar_flag: Mapped[str] = mapped_column(String(10), nullable=False, default="🏴")
    is_setup: Mapped[bool] = mapped_column(default=False)
    # Puntos iniciales (handicap) por jugador; se suman al total. Vienen del CSV.
    initial_points: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Admin: puede corregir predicciones de partidos cerrados. Viene del CSV.
    is_admin: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )

    # relationships
    predictions: Mapped[list["Prediction"]] = relationship(
        back_populates="player", cascade="all, delete-orphan"
    )
    match_scores: Mapped[list["MatchScore"]] = relationship(
        back_populates="player", cascade="all, delete-orphan"
    )
    standings_snapshots: Mapped[list["StandingsSnapshot"]] = relationship(
        back_populates="player", cascade="all, delete-orphan"
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "avatar_flag": self.avatar_flag,
            "is_setup": self.is_setup,
            "initial_points": self.initial_points,
            "is_admin": self.is_admin,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

    def __repr__(self) -> str:
        return f"<Player(id={self.id}, name={self.name!r})>"


class Match(Base):
    __tablename__ = "matches"
    __table_args__ = (UniqueConstraint("external_id", name="uq_match_external_id"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    external_id: Mapped[str] = mapped_column(
        String(50), unique=True, nullable=False
    )
    home: Mapped[Optional[str]] = mapped_column(
        String(100), nullable=True, default=None
    )  # null = TBD
    away: Mapped[Optional[str]] = mapped_column(
        String(100), nullable=True, default=None
    )  # null = TBD
    home_flag: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    away_flag: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    kickoff_utc: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    match_date_local: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    stage: Mapped[str] = mapped_column(String(50), nullable=False, default="group")
    status: Mapped[MatchStatus] = mapped_column(
        Enum(MatchStatus), nullable=False, default=MatchStatus.SCHEDULED
    )
    goals_home: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    goals_away: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )

    # relationships
    predictions: Mapped[list["Prediction"]] = relationship(
        back_populates="match", cascade="all, delete-orphan"
    )
    match_scores: Mapped[list["MatchScore"]] = relationship(
        back_populates="match", cascade="all, delete-orphan"
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "external_id": self.external_id,
            "home": self.home,
            "away": self.away,
            "home_flag": self.home_flag,
            "away_flag": self.away_flag,
            "kickoff_utc": self.kickoff_utc.isoformat() if self.kickoff_utc else None,
            "match_date_local": (
                self.match_date_local.isoformat() if self.match_date_local else None
            ),
            "stage": self.stage,
            "status": self.status.value if self.status else None,
            "goals_home": self.goals_home,
            "goals_away": self.goals_away,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

    def __repr__(self) -> str:
        return f"<Match(id={self.id}, {self.home} vs {self.away}, status={self.status})>"


class Prediction(Base):
    __tablename__ = "predictions"
    __table_args__ = (
        UniqueConstraint("player_id", "match_id", name="uq_prediction_player_match"),
        CheckConstraint("pred_home >= 0 AND pred_home <= 100", name="ck_pred_home_range"),
        CheckConstraint("pred_away >= 0 AND pred_away <= 100", name="ck_pred_away_range"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    player_id: Mapped[int] = mapped_column(
        ForeignKey("players.id"), nullable=False, index=True
    )
    match_id: Mapped[int] = mapped_column(
        ForeignKey("matches.id"), nullable=False, index=True
    )
    pred_home: Mapped[int] = mapped_column(Integer, nullable=False)  # 0-100
    pred_away: Mapped[int] = mapped_column(Integer, nullable=False)  # 0-100
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )

    # relationships
    player: Mapped["Player"] = relationship(back_populates="predictions")
    match: Mapped["Match"] = relationship(back_populates="predictions")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "player_id": self.player_id,
            "match_id": self.match_id,
            "pred_home": self.pred_home,
            "pred_away": self.pred_away,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

    def __repr__(self) -> str:
        return (
            f"<Prediction(player={self.player_id}, match={self.match_id}, "
            f"{self.pred_home}-{self.pred_away})>"
        )


class MatchScore(Base):
    __tablename__ = "match_scores"
    __table_args__ = (
        UniqueConstraint(
            "player_id", "match_id", name="uq_matchscore_player_match"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    player_id: Mapped[int] = mapped_column(
        ForeignKey("players.id"), nullable=False, index=True
    )
    match_id: Mapped[int] = mapped_column(
        ForeignKey("matches.id"), nullable=False, index=True
    )
    points: Mapped[int] = mapped_column(Integer, nullable=False)  # 0, 2, or 4
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )

    # relationships
    player: Mapped["Player"] = relationship(back_populates="match_scores")
    match: Mapped["Match"] = relationship(back_populates="match_scores")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "player_id": self.player_id,
            "match_id": self.match_id,
            "points": self.points,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

    def __repr__(self) -> str:
        return (
            f"<MatchScore(player={self.player_id}, match={self.match_id}, "
            f"points={self.points})>"
        )


class StandingsSnapshot(Base):
    __tablename__ = "standings_snapshots"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    player_id: Mapped[int] = mapped_column(
        ForeignKey("players.id"), nullable=False, index=True
    )
    snapshot_date_local: Mapped[date] = mapped_column(
        Date, nullable=False, default=date.today
    )
    total_points: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    rank: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )

    # relationships
    player: Mapped["Player"] = relationship(back_populates="standings_snapshots")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "player_id": self.player_id,
            "snapshot_date_local": (
                self.snapshot_date_local.isoformat()
                if self.snapshot_date_local
                else None
            ),
            "total_points": self.total_points,
            "rank": self.rank,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

    def __repr__(self) -> str:
        return (
            f"<StandingsSnapshot(player={self.player_id}, "
            f"date={self.snapshot_date_local}, rank={self.rank})>"
        )


class AdminAuditLog(Base):
    """Registro de correcciones hechas por un admin sobre predicciones cerradas."""

    __tablename__ = "admin_audit_log"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    admin_id: Mapped[int] = mapped_column(ForeignKey("players.id"), nullable=False)
    match_id: Mapped[int] = mapped_column(ForeignKey("matches.id"), nullable=False)
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id"), nullable=False)
    old_pred_home: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    old_pred_away: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    new_pred_home: Mapped[int] = mapped_column(Integer, nullable=False)
    new_pred_away: Mapped[int] = mapped_column(Integer, nullable=False)
    old_points: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    new_points: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "admin_id": self.admin_id,
            "match_id": self.match_id,
            "player_id": self.player_id,
            "old_pred_home": self.old_pred_home,
            "old_pred_away": self.old_pred_away,
            "new_pred_home": self.new_pred_home,
            "new_pred_away": self.new_pred_away,
            "old_points": self.old_points,
            "new_points": self.new_points,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

    def __repr__(self) -> str:
        return (
            f"<AdminAuditLog(admin={self.admin_id}, match={self.match_id}, "
            f"player={self.player_id}, {self.old_points}->{self.new_points})>"
        )
