"""Restrict the public schema to the FastAPI database connection.

Revision ID: 20261015_0005
Revises: 20261015_0004
"""

from alembic import op

revision = "20261015_0005"
down_revision = "20261015_0004"
branch_labels = None
depends_on = None

PROTECTED_TABLES = (
    "alembic_version",
    "data_sources",
    "stations",
    "users",
    "groundwater_observations",
    "hotspots",
    "priority_assessments",
    "inspection_tasks",
    "field_reports",
    "task_status_history",
    "data_import_runs",
    "firms_sync_runs",
)

NON_WORKFLOW_TABLES = tuple(
    table
    for table in PROTECTED_TABLES
    if table not in {"users", "inspection_tasks", "field_reports", "task_status_history"}
)


def upgrade() -> None:
    for table in PROTECTED_TABLES:
        op.execute(f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY")

    table_list = ", ".join(f"public.{table}" for table in PROTECTED_TABLES)
    op.execute(
        f"""
        DO $$
        BEGIN
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
            REVOKE ALL ON TABLE {table_list} FROM anon;
            ALTER DEFAULT PRIVILEGES IN SCHEMA public
              REVOKE ALL ON TABLES FROM anon;
          END IF;
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
            REVOKE ALL ON TABLE {table_list} FROM authenticated;
            ALTER DEFAULT PRIVILEGES IN SCHEMA public
              REVOKE ALL ON TABLES FROM authenticated;
          END IF;
        END $$;
        """
    )

def downgrade() -> None:
    # The four workflow tables already had RLS in revision 0004.
    for table in NON_WORKFLOW_TABLES:
        op.execute(f"ALTER TABLE public.{table} DISABLE ROW LEVEL SECURITY")

