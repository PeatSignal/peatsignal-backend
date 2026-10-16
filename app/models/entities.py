import uuid
from datetime import date, datetime
from typing import Any

from geoalchemy2 import Geometry
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class DataSource(Base):
    __tablename__ = "data_sources"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    url: Mapped[str | None] = mapped_column(Text)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    imported_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class DataImportRun(Base):
    __tablename__ = "data_import_runs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    source_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("data_sources.id", ondelete="CASCADE"), nullable=False
    )
    dataset_kind: Mapped[str] = mapped_column(String(30), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    rows_seen: Mapped[int] = mapped_column(nullable=False, server_default="0")
    rows_inserted: Mapped[int] = mapped_column(nullable=False, server_default="0")
    rows_skipped: Mapped[int] = mapped_column(nullable=False, server_default="0")
    audit_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint("dataset_kind IN ('GROUNDWATER', 'HOTSPOT')", name="dataset_kind_value"),
        CheckConstraint("status IN ('STARTED', 'COMPLETED', 'FAILED')", name="status_value"),
        Index("ix_data_import_runs_source_started", "source_id", "started_at"),
    )


class FirmsSyncRun(Base):
    __tablename__ = "firms_sync_runs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    area_id: Mapped[str] = mapped_column(String(30), nullable=False)
    source_product: Mapped[str] = mapped_column(String(40), nullable=False)
    day_range: Mapped[int] = mapped_column(nullable=False)
    date_from: Mapped[date] = mapped_column(Date, nullable=False)
    date_to: Mapped[date] = mapped_column(Date, nullable=False)
    actor_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rows_received: Mapped[int] = mapped_column(nullable=False, default=0)
    rows_inserted: Mapped[int] = mapped_column(nullable=False, default=0)
    rows_conflicts: Mapped[int] = mapped_column(nullable=False, default=0)
    error_code: Mapped[str | None] = mapped_column(String(50))
    source_sha256: Mapped[str | None] = mapped_column(String(64))

    __table_args__ = (
        CheckConstraint("status IN ('RUNNING', 'SUCCESS', 'FAILED')", name="status_value"),
        CheckConstraint("day_range BETWEEN 1 AND 5", name="day_range_value"),
        CheckConstraint("area_id IN ('batanghari', 'kubu-raya', 'indonesia')", name="area_value"),
        CheckConstraint(
            "source_product IN ('VIIRS_SNPP_NRT', 'VIIRS_NOAA20_NRT')", name="product_value"
        ),
        Index("ix_firms_sync_runs_target_started", "area_id", "source_product", "started_at"),
    )


class Station(Base, TimestampMixin):
    __tablename__ = "stations"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)
    region: Mapped[str | None] = mapped_column(String(200))
    latitude: Mapped[float | None] = mapped_column(Float)
    longitude: Mapped[float | None] = mapped_column(Float)
    coordinate_source: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        CheckConstraint("latitude IS NULL OR latitude BETWEEN -90 AND 90", name="latitude_range"),
        CheckConstraint(
            "longitude IS NULL OR longitude BETWEEN -180 AND 180", name="longitude_range"
        ),
        CheckConstraint(
            "(latitude IS NULL AND longitude IS NULL) OR "
            "(latitude IS NOT NULL AND longitude IS NOT NULL AND coordinate_source IS NOT NULL)",
            name="coordinates_require_source",
        ),
    )


class GroundwaterObservation(Base):
    __tablename__ = "groundwater_observations"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    station_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("stations.id", ondelete="CASCADE"), nullable=False
    )
    observed_date: Mapped[date] = mapped_column(Date, nullable=False)
    gwt_m: Mapped[float | None] = mapped_column(Float)
    quality_flag: Mapped[str] = mapped_column(String(30), nullable=False)
    mode: Mapped[str] = mapped_column(
        String(30), nullable=False, server_default="HISTORICAL_REPLAY"
    )
    source_row_number: Mapped[int | None] = mapped_column()
    source_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("data_sources.id", ondelete="RESTRICT"), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("station_id", "observed_date"),
        CheckConstraint(
            "quality_flag IN ('VALID', 'MISSING', 'DUPLICATE', 'SUSPECT')",
            name="quality_flag_value",
        ),
        CheckConstraint(
            "mode IN ('HISTORICAL_REPLAY', 'CURRENT_MONITORING')", name="mode_value"
        ),
        Index("ix_groundwater_station_date", "station_id", "observed_date"),
        Index("ix_groundwater_mode_date", "mode", "observed_date"),
    )


class Hotspot(Base, TimestampMixin):
    __tablename__ = "hotspots"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    external_key: Mapped[str] = mapped_column(String(180), nullable=False, unique=True)
    source_product: Mapped[str] = mapped_column(String(80), nullable=False)
    sensor: Mapped[str] = mapped_column(String(80), nullable=False)
    satellite: Mapped[str] = mapped_column(String(80), nullable=False)
    acquired_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    geom: Mapped[Any] = mapped_column(
        Geometry(geometry_type="POINT", srid=4326, spatial_index=False), nullable=False
    )
    frp: Mapped[float | None] = mapped_column(Float)
    confidence_raw: Mapped[str | None] = mapped_column(String(30))
    quality_flag: Mapped[str] = mapped_column(String(30), nullable=False, server_default="VALID")
    mode: Mapped[str] = mapped_column(
        String(30), nullable=False, server_default="HISTORICAL_REPLAY"
    )
    source_row_number: Mapped[int | None] = mapped_column()
    verification_status: Mapped[str] = mapped_column(
        String(30), nullable=False, server_default="UNVERIFIED"
    )
    source_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("data_sources.id", ondelete="RESTRICT"), nullable=False
    )
    last_synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        CheckConstraint(
            "verification_status IN ('UNVERIFIED', 'VERIFIED', 'DISMISSED')",
            name="verification_status_value",
        ),
        CheckConstraint(
            "quality_flag IN ('VALID', 'SUSPECT')", name="quality_flag_value"
        ),
        CheckConstraint(
            "mode IN ('HISTORICAL_REPLAY', 'CURRENT_MONITORING')", name="mode_value"
        ),
        Index("ix_hotspots_acquired_at", "acquired_at"),
        Index("ix_hotspots_mode_acquired", "mode", "acquired_at"),
        Index("ix_hotspots_geom", "geom", postgresql_using="gist"),
    )


class PriorityAssessment(Base):
    __tablename__ = "priority_assessments"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    mode: Mapped[str] = mapped_column(String(30), nullable=False)
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    priority: Mapped[str] = mapped_column(String(30), nullable=False)
    explanation: Mapped[str] = mapped_column(Text, nullable=False)
    reasons_json: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    missing_inputs_json: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    inputs_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    recommended_actions_json: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    rule_version: Mapped[str] = mapped_column(String(50), nullable=False)
    scientific_status: Mapped[str] = mapped_column(
        String(50), nullable=False, server_default="heuristic_not_validated"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint(
            "mode IN ('HISTORICAL_REPLAY', 'CURRENT_MONITORING')", name="mode_value"
        ),
        CheckConstraint(
            "priority IN ('LOW', 'MEDIUM', 'HIGH', 'INSUFFICIENT_DATA')",
            name="priority_value",
        ),
        CheckConstraint(
            "scientific_status = 'heuristic_not_validated'", name="scientific_status_value"
        ),
        Index("ix_priority_assessments_mode_as_of", "mode", "as_of"),
    )


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    role: Mapped[str] = mapped_column(String(30), nullable=False)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")

    __table_args__ = (
        CheckConstraint("role IN ('coordinator', 'field_officer')", name="role_value"),
    )


class InspectionTask(Base, TimestampMixin):
    __tablename__ = "inspection_tasks"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    assessment_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("priority_assessments.id", ondelete="SET NULL")
    )
    hotspot_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("hotspots.id", ondelete="SET NULL")
    )
    status: Mapped[str] = mapped_column(String(30), nullable=False, server_default="OPEN")
    mode: Mapped[str] = mapped_column(String(30), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    priority: Mapped[str] = mapped_column(String(30), nullable=False)
    area_id: Mapped[str | None] = mapped_column(String(30))
    assignee_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    created_by_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    note: Mapped[str | None] = mapped_column(Text)
    is_simulation: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")

    __table_args__ = (
        CheckConstraint(
            "status IN ('OPEN', 'ASSIGNED', 'IN_PROGRESS', 'SUBMITTED', 'VERIFIED', "
            "'DISMISSED', 'NEEDS_FOLLOWUP')",
            name="status_value",
        ),
        CheckConstraint(
            "priority IN ('LOW', 'MEDIUM', 'HIGH', 'INSUFFICIENT_DATA')",
            name="priority_value",
        ),
        CheckConstraint(
            "mode IN ('HISTORICAL_REPLAY', 'CURRENT_MONITORING')", name="mode_value"
        ),
        CheckConstraint(
            "area_id IS NULL OR area_id IN ('batanghari', 'kubu-raya')", name="area_value"
        ),
        Index("ix_inspection_tasks_status_assignee", "status", "assignee_id"),
        Index("ix_inspection_tasks_assessment_id", "assessment_id"),
        Index("ix_inspection_tasks_hotspot_id", "hotspot_id"),
        Index("ix_inspection_tasks_assignee_id", "assignee_id"),
        Index("ix_inspection_tasks_created_by_id", "created_by_id"),
        Index("ix_inspection_tasks_mode_updated", "mode", "updated_at"),
    )


class FieldReport(Base):
    __tablename__ = "field_reports"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    task_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("inspection_tasks.id", ondelete="CASCADE"), nullable=False
    )
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    result: Mapped[str] = mapped_column(String(100), nullable=False)
    note: Mapped[str] = mapped_column(Text, nullable=False)
    is_simulation: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    evidence_url: Mapped[str | None] = mapped_column(Text)
    submitted_by_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint(
            "result IN ('ACTIVE_FIRE_FOUND', 'BURN_SCAR_FOUND', 'NO_FIRE_FOUND', "
            "'LOCATION_INACCESSIBLE')",
            name="result_value",
        ),
        Index("ix_field_reports_task_id", "task_id"),
        Index("ix_field_reports_submitted_by_id", "submitted_by_id"),
    )


class TaskStatusHistory(Base):
    __tablename__ = "task_status_history"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    task_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("inspection_tasks.id", ondelete="CASCADE"), nullable=False
    )
    from_status: Mapped[str | None] = mapped_column(String(30))
    to_status: Mapped[str] = mapped_column(String(30), nullable=False)
    actor_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    actor_role: Mapped[str] = mapped_column(String(30), nullable=False)
    changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    note: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        CheckConstraint(
            "from_status IS NULL OR from_status IN ('OPEN', 'ASSIGNED', 'IN_PROGRESS', "
            "'SUBMITTED', 'VERIFIED', 'DISMISSED', 'NEEDS_FOLLOWUP')",
            name="from_status_value",
        ),
        CheckConstraint(
            "to_status IN ('OPEN', 'ASSIGNED', 'IN_PROGRESS', 'SUBMITTED', 'VERIFIED', "
            "'DISMISSED', 'NEEDS_FOLLOWUP')",
            name="to_status_value",
        ),
        CheckConstraint(
            "actor_role IN ('coordinator', 'field_officer')", name="actor_role_value"
        ),
        Index("ix_task_status_history_task_changed", "task_id", "changed_at"),
        Index("ix_task_status_history_actor_id", "actor_id"),
    )

