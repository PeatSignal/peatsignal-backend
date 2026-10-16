"""Persist FIRMS sync attempts.

Revision ID: 20261015_0003
Revises: 20261014_0002
"""
import sqlalchemy as sa

from alembic import op

revision = "20261015_0003"
down_revision = "20261014_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "firms_sync_runs",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("area_id", sa.String(30), nullable=False),
        sa.Column("source_product", sa.String(40), nullable=False),
        sa.Column("day_range", sa.Integer(), nullable=False),
        sa.Column("date_from", sa.Date(), nullable=False),
        sa.Column("date_to", sa.Date(), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("rows_received", sa.Integer(), nullable=False),
        sa.Column("rows_inserted", sa.Integer(), nullable=False),
        sa.Column("rows_conflicts", sa.Integer(), nullable=False),
        sa.Column("error_code", sa.String(50)),
        sa.Column("source_sha256", sa.String(64)),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"], ondelete="RESTRICT"),
        sa.CheckConstraint("status IN ('RUNNING', 'SUCCESS', 'FAILED')", name="status_value"),
        sa.CheckConstraint("day_range BETWEEN 1 AND 5", name="day_range_value"),
        sa.CheckConstraint("area_id IN ('batanghari', 'kubu-raya')", name="area_value"),
        sa.CheckConstraint(
            "source_product IN ('VIIRS_SNPP_NRT', 'VIIRS_NOAA20_NRT')", name="product_value"
        ),
    )
    op.create_index(
        "ix_firms_sync_runs_target_started", "firms_sync_runs",
        ["area_id", "source_product", "started_at"],
    )
    op.create_index("ix_firms_sync_runs_actor_id", "firms_sync_runs", ["actor_id"])


def downgrade() -> None:
    op.drop_table("firms_sync_runs")
