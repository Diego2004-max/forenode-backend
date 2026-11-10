from datetime import date, datetime, timezone

from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Integer, LargeBinary, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "forenode_users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255))
    full_name: Mapped[str] = mapped_column(String(160))
    role: Mapped[str] = mapped_column(String(40), default="viewer")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class RegionNode(Base):
    __tablename__ = "region_nodes"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120))
    latitude: Mapped[float] = mapped_column(Float)
    longitude: Mapped[float] = mapped_column(Float)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)


class InventorySnapshot(Base):
    __tablename__ = "inventory_snapshots"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_code: Mapped[str] = mapped_column(String(40), index=True)
    region_code: Mapped[str] = mapped_column(String(40), index=True)
    quantity_kg: Mapped[float] = mapped_column(Float)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    source_reference: Mapped[str] = mapped_column(String(500))
    created_by: Mapped[int] = mapped_column(ForeignKey("forenode_users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class DemandObservation(Base):
    __tablename__ = "demand_observations"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_code: Mapped[str] = mapped_column(String(40), index=True)
    region_code: Mapped[str] = mapped_column(String(40), index=True)
    observed_on: Mapped[date] = mapped_column(Date, index=True)
    demand_kg: Mapped[float] = mapped_column(Float)
    temperature_c: Mapped[float] = mapped_column(Float)
    precipitation_mm: Mapped[float] = mapped_column(Float)
    source_reference: Mapped[str] = mapped_column(String(500))
    is_valid: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    created_by: Mapped[int] = mapped_column(ForeignKey("forenode_users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class ModelArtifact(Base):
    __tablename__ = "model_artifacts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_code: Mapped[str] = mapped_column(String(40), index=True)
    region_code: Mapped[str] = mapped_column(String(40), index=True)
    version: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    training_rows: Mapped[int] = mapped_column(Integer)
    mae_kg: Mapped[float] = mapped_column(Float)
    r2_score: Mapped[float] = mapped_column(Float)
    residual_p90_kg: Mapped[float] = mapped_column(Float)
    artifact: Mapped[bytes] = mapped_column(LargeBinary)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    trained_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class MatchingRun(Base):
    __tablename__ = "matching_runs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_code: Mapped[str] = mapped_column(String(40), index=True)
    region_code: Mapped[str] = mapped_column(String(40), index=True)
    target_date: Mapped[date] = mapped_column(Date)
    predicted_demand_kg: Mapped[float] = mapped_column(Float)
    available_supply_kg: Mapped[float] = mapped_column(Float)
    gap_kg: Mapped[float] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(40))
    confidence_score: Mapped[float] = mapped_column(Float)
    model_version: Mapped[str] = mapped_column(String(64))
    weather_source: Mapped[str] = mapped_column(String(500))
    inventory_snapshot_id: Mapped[int] = mapped_column(ForeignKey("inventory_snapshots.id"))
    requested_by: Mapped[int] = mapped_column(ForeignKey("forenode_users.id"))
    explanation: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
