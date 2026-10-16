"""Add mode separation and import provenance.

Revision ID: 20261014_0002
Revises: 20261014_0001
Create Date: 2026-10-14
"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20261014_0002"
down_revision: str | None = "20261014_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "groundwater_observations",
        sa.Column(
            "mode",
            sa.String(length=30),
            server_default="HISTORICAL_REPLAY",
            nullable=False,
        ),
    )
    op.add_column(
        "groundwater_observations", sa.Column("source_row_number", sa.Integer())
    )
    op.create_check_constraint(
        "ck_groundwater_observations_mode_value",
        "groundwater_observations",
        "mode IN ('HISTORICAL_REPLAY', 'CURRENT_MONITORING')",
    )
    op.create_index(
        "ix_groundwater_mode_date", "groundwater_observations", ["mode", "observed_date"]
    )

    op.add_column(
        "hotspots",
        sa.Column("satellite", sa.String(length=80), server_default="UNKNOWN", nullable=False),
    )
    op.add_column(
        "hotspots",
        sa.Column("quality_flag", sa.String(length=30), server_default="VALID", nullable=False),
    )
    op.add_column(
        "hotspots",
        sa.Column(
            "mode",
            sa.String(length=30),
            server_default="HISTORICAL_REPLAY",
            nullable=False,
        ),
    )
    op.add_column("hotspots", sa.Column("source_row_number", sa.Integer()))
    op.create_check_constraint(
        "ck_hotspots_quality_flag_value",
        "hotspots",
        "quality_flag IN ('VALID', 'SUSPECT')",
    )
    op.create_check_constraint(
        "ck_hotspots_mode_value",
        "hotspots",
        "mode IN ('HISTORICAL_REPLAY', 'CURRENT_MONITORING')",
    )
    op.create_index("ix_hotspots_mode_acquired", "hotspots", ["mode", "acquired_at"])

    op.create_table(
        "data_import_runs",
        sa.Column(
            "id",
            sa.Uuid(),
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
            nullable=False,
        ),
        sa.Column("source_id", sa.Uuid(), nullable=False),
        sa.Column("dataset_kind", sa.String(length=30), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("rows_seen", sa.Integer(), server_default="0", nullable=False),
        sa.Column("rows_inserted", sa.Integer(), server_default="0", nullable=False),
        sa.Column("rows_skipped", sa.Integer(), server_default="0", nullable=False),
        sa.Column("audit_json", postgresql.JSONB(), nullable=False),
        sa.Column(
            "started_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "dataset_kind IN ('GROUNDWATER', 'HOTSPOT')",
            name="ck_data_import_runs_dataset_kind_value",
        ),
        sa.CheckConstraint(
            "status IN ('STARTED', 'COMPLETED', 'FAILED')",
            name="ck_data_import_runs_status_value",
        ),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["data_sources.id"],
            ondelete="CASCADE",
            name="fk_data_import_runs_source_id_data_sources",
        ),
    )
    op.create_index(
        "ix_data_import_runs_source_started", "data_import_runs", ["source_id", "started_at"]
    )


def downgrade() -> None:
    op.drop_table("data_import_runs")
    op.drop_index("ix_hotspots_mode_acquired", table_name="hotspots")
    op.drop_constraint("ck_hotspots_mode_value", "hotspots", type_="check")
    op.drop_constraint("ck_hotspots_quality_flag_value", "hotspots", type_="check")
    op.drop_column("hotspots", "source_row_number")
    op.drop_column("hotspots", "mode")
    op.drop_column("hotspots", "quality_flag")
    op.drop_column("hotspots", "satellite")
    op.drop_index("ix_groundwater_mode_date", table_name="groundwater_observations")
    op.drop_constraint(
        "ck_groundwater_observations_mode_value",
        "groundwater_observations",
        type_="check",
    )
    op.drop_column("groundwater_observations", "source_row_number")
    op.drop_column("groundwater_observations", "mode")
