"""Allow nationwide NASA FIRMS synchronization.

Revision ID: 20261015_0006
Revises: 20261015_0005
"""

from alembic import op

revision = "20261015_0006"
down_revision = "20261015_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint(op.f("ck_firms_sync_runs_area_value"), "firms_sync_runs", type_="check")
    op.create_check_constraint(
        "area_value", "firms_sync_runs",
        "area_id IN ('batanghari', 'kubu-raya', 'indonesia')",
    )


def downgrade() -> None:
    # Downgrade requires nationwide sync history to be archived first.
    op.drop_constraint(op.f("ck_firms_sync_runs_area_value"), "firms_sync_runs", type_="check")
    op.create_check_constraint(
        "area_value", "firms_sync_runs", "area_id IN ('batanghari', 'kubu-raya')",
    )
