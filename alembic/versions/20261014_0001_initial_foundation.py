"""Create the GambutOps foundation schema.

Revision ID: 20261014_0001
Revises:
Create Date: 2026-10-14
"""
from collections.abc import Sequence

import geoalchemy2
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20261014_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def uuid_column() -> sa.Column[object]:
    return sa.Column(
        "id",
        sa.Uuid(),
        primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
        nullable=False,
    )


def timestamps() -> tuple[sa.Column[object], sa.Column[object]]:
    return (
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis")
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")

    op.create_table(
        "data_sources",
        uuid_column(),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("url", sa.Text()),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column(
            "imported_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("sha256", name="uq_data_sources_sha256"),
    )
    op.create_table(
        "stations",
        uuid_column(),
        sa.Column("code", sa.String(length=50), nullable=False),
        sa.Column("region", sa.String(length=200)),
        sa.Column("latitude", sa.Float()),
        sa.Column("longitude", sa.Float()),
        sa.Column("coordinate_source", sa.Text()),
        *timestamps(),
        sa.CheckConstraint(
            "latitude IS NULL OR latitude BETWEEN -90 AND 90", name="ck_stations_latitude_range"
        ),
        sa.CheckConstraint(
            "longitude IS NULL OR longitude BETWEEN -180 AND 180",
            name="ck_stations_longitude_range",
        ),
        sa.CheckConstraint(
            "(latitude IS NULL AND longitude IS NULL) OR "
            "(latitude IS NOT NULL AND longitude IS NOT NULL AND coordinate_source IS NOT NULL)",
            name="ck_stations_coordinates_require_source",
        ),
        sa.UniqueConstraint("code", name="uq_stations_code"),
    )
    op.create_table(
        "users",
        uuid_column(),
        sa.Column("role", sa.String(length=30), nullable=False),
        sa.Column("display_name", sa.String(length=200), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        *timestamps(),
        sa.CheckConstraint(
            "role IN ('coordinator', 'field_officer')", name="ck_users_role_value"
        ),
    )
    users_table = sa.table(
        "users",
        sa.column("id", sa.Uuid()),
        sa.column("role", sa.String()),
        sa.column("display_name", sa.String()),
        sa.column("is_active", sa.Boolean()),
    )
    op.bulk_insert(
        users_table,
        [
            {
                "id": "00000000-0000-4000-8000-000000000001",
                "role": "coordinator",
                "display_name": "Koordinator Demo",
                "is_active": True,
            },
            {
                "id": "00000000-0000-4000-8000-000000000002",
                "role": "field_officer",
                "display_name": "Petugas Lapangan Demo",
                "is_active": True,
            },
        ],
    )
    op.create_table(
        "groundwater_observations",
        uuid_column(),
        sa.Column("station_id", sa.Uuid(), nullable=False),
        sa.Column("observed_date", sa.Date(), nullable=False),
        sa.Column("gwt_m", sa.Float()),
        sa.Column("quality_flag", sa.String(length=30), nullable=False),
        sa.Column("source_id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "quality_flag IN ('VALID', 'MISSING', 'DUPLICATE', 'SUSPECT')",
            name="ck_groundwater_observations_quality_flag_value",
        ),
        sa.ForeignKeyConstraint(
            ["source_id"], ["data_sources.id"], ondelete="RESTRICT", name="fk_gwo_source"
        ),
        sa.ForeignKeyConstraint(
            ["station_id"], ["stations.id"], ondelete="CASCADE", name="fk_gwo_station"
        ),
        sa.UniqueConstraint(
            "station_id", "observed_date", name="uq_groundwater_station_observed_date"
        ),
    )
    op.create_index(
        "ix_groundwater_station_date",
        "groundwater_observations",
        ["station_id", "observed_date"],
    )
    op.create_table(
        "hotspots",
        uuid_column(),
        sa.Column("external_key", sa.String(length=180), nullable=False),
        sa.Column("source_product", sa.String(length=80), nullable=False),
        sa.Column("sensor", sa.String(length=80), nullable=False),
        sa.Column("acquired_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "geom",
            geoalchemy2.Geometry("POINT", srid=4326, spatial_index=False),
            nullable=False,
        ),
        sa.Column("frp", sa.Float()),
        sa.Column("confidence_raw", sa.String(length=30)),
        sa.Column(
            "verification_status",
            sa.String(length=30),
            server_default="UNVERIFIED",
            nullable=False,
        ),
        sa.Column("source_id", sa.Uuid(), nullable=False),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=False),
        *timestamps(),
        sa.CheckConstraint(
            "verification_status IN ('UNVERIFIED', 'VERIFIED', 'DISMISSED')",
            name="ck_hotspots_verification_status_value",
        ),
        sa.ForeignKeyConstraint(
            ["source_id"], ["data_sources.id"], ondelete="RESTRICT", name="fk_hotspots_source"
        ),
        sa.UniqueConstraint("external_key", name="uq_hotspots_external_key"),
    )
    op.create_index("ix_hotspots_acquired_at", "hotspots", ["acquired_at"])
    op.create_index("ix_hotspots_geom", "hotspots", ["geom"], postgresql_using="gist")
    op.create_table(
        "priority_assessments",
        uuid_column(),
        sa.Column("mode", sa.String(length=30), nullable=False),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column("priority", sa.String(length=30), nullable=False),
        sa.Column("explanation", sa.Text(), nullable=False),
        sa.Column("reasons_json", postgresql.JSONB(), nullable=False),
        sa.Column("missing_inputs_json", postgresql.JSONB(), nullable=False),
        sa.Column("inputs_json", postgresql.JSONB(), nullable=False),
        sa.Column("recommended_actions_json", postgresql.JSONB(), nullable=False),
        sa.Column("rule_version", sa.String(length=50), nullable=False),
        sa.Column(
            "scientific_status",
            sa.String(length=50),
            server_default="heuristic_not_validated",
            nullable=False,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "mode IN ('HISTORICAL_REPLAY', 'CURRENT_MONITORING')",
            name="ck_priority_assessments_mode_value",
        ),
        sa.CheckConstraint(
            "priority IN ('LOW', 'MEDIUM', 'HIGH', 'INSUFFICIENT_DATA')",
            name="ck_priority_assessments_priority_value",
        ),
        sa.CheckConstraint(
            "scientific_status = 'heuristic_not_validated'",
            name="ck_priority_assessments_scientific_status_value",
        ),
    )
    op.create_index(
        "ix_priority_assessments_mode_as_of", "priority_assessments", ["mode", "as_of"]
    )
    op.create_table(
        "inspection_tasks",
        uuid_column(),
        sa.Column("assessment_id", sa.Uuid()),
        sa.Column("hotspot_id", sa.Uuid()),
        sa.Column("status", sa.String(length=30), server_default="OPEN", nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("priority", sa.String(length=30), nullable=False),
        sa.Column("assignee_id", sa.Uuid()),
        sa.Column("created_by_id", sa.Uuid(), nullable=False),
        *timestamps(),
        sa.CheckConstraint(
            "status IN ('OPEN', 'ASSIGNED', 'IN_PROGRESS', 'SUBMITTED', 'VERIFIED', "
            "'DISMISSED', 'NEEDS_FOLLOWUP')",
            name="ck_inspection_tasks_status_value",
        ),
        sa.CheckConstraint(
            "priority IN ('LOW', 'MEDIUM', 'HIGH', 'INSUFFICIENT_DATA')",
            name="ck_inspection_tasks_priority_value",
        ),
        sa.ForeignKeyConstraint(
            ["assessment_id"],
            ["priority_assessments.id"],
            ondelete="SET NULL",
            name="fk_tasks_assessment",
        ),
        sa.ForeignKeyConstraint(
            ["hotspot_id"], ["hotspots.id"], ondelete="SET NULL", name="fk_tasks_hotspot"
        ),
        sa.ForeignKeyConstraint(
            ["assignee_id"], ["users.id"], ondelete="SET NULL", name="fk_tasks_assignee"
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"], ["users.id"], ondelete="RESTRICT", name="fk_tasks_creator"
        ),
    )
    op.create_index(
        "ix_inspection_tasks_status_assignee", "inspection_tasks", ["status", "assignee_id"]
    )
    op.create_table(
        "field_reports",
        uuid_column(),
        sa.Column("task_id", sa.Uuid(), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("result", sa.String(length=100), nullable=False),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("is_simulation", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("evidence_url", sa.Text()),
        sa.Column("submitted_by_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["task_id"], ["inspection_tasks.id"], ondelete="CASCADE", name="fk_reports_task"
        ),
        sa.ForeignKeyConstraint(
            ["submitted_by_id"],
            ["users.id"],
            ondelete="RESTRICT",
            name="fk_reports_submitter",
        ),
    )
    op.create_table(
        "task_status_history",
        uuid_column(),
        sa.Column("task_id", sa.Uuid(), nullable=False),
        sa.Column("from_status", sa.String(length=30)),
        sa.Column("to_status", sa.String(length=30), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=False),
        sa.Column(
            "changed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["task_id"], ["inspection_tasks.id"], ondelete="CASCADE", name="fk_history_task"
        ),
        sa.ForeignKeyConstraint(
            ["actor_id"], ["users.id"], ondelete="RESTRICT", name="fk_history_actor"
        ),
    )
    op.create_index(
        "ix_task_status_history_task_changed", "task_status_history", ["task_id", "changed_at"]
    )


def downgrade() -> None:
    op.drop_table("task_status_history")
    op.drop_table("field_reports")
    op.drop_table("inspection_tasks")
    op.drop_table("priority_assessments")
    op.drop_table("hotspots")
    op.drop_table("groundwater_observations")
    op.drop_table("users")
    op.drop_table("stations")
    op.drop_table("data_sources")

