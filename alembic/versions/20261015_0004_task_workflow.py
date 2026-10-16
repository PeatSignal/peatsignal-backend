"""Complete the field task and report workflow schema.

Revision ID: 20261015_0004
Revises: 20261015_0003
"""

import sqlalchemy as sa

from alembic import op

revision = "20261015_0004"
down_revision = "20261015_0003"
branch_labels = None
depends_on = None

WORKFLOW_TABLES = ("users", "inspection_tasks", "field_reports", "task_status_history")


def upgrade() -> None:
    op.add_column("inspection_tasks", sa.Column("mode", sa.String(30), nullable=True))
    op.add_column("inspection_tasks", sa.Column("area_id", sa.String(30)))
    op.add_column("inspection_tasks", sa.Column("note", sa.Text()))
    op.add_column(
        "inspection_tasks",
        sa.Column("is_simulation", sa.Boolean(), server_default=sa.true(), nullable=False),
    )
    op.execute(
        """
        UPDATE inspection_tasks AS task
        SET mode = COALESCE(assessment.mode, 'HISTORICAL_REPLAY'),
            area_id = COALESCE(assessment.inputs_json ->> 'area_id', task.area_id)
        FROM priority_assessments AS assessment
        WHERE task.assessment_id = assessment.id
        """
    )
    op.execute(
        """
        UPDATE inspection_tasks AS task
        SET mode = COALESCE(task.mode, hotspot.mode, 'HISTORICAL_REPLAY')
        FROM hotspots AS hotspot
        WHERE task.hotspot_id = hotspot.id
        """
    )
    op.execute(
        "UPDATE inspection_tasks SET mode = 'HISTORICAL_REPLAY' WHERE mode IS NULL"
    )
    op.alter_column("inspection_tasks", "mode", nullable=False)

    op.create_check_constraint(
        op.f("ck_inspection_tasks_mode_value"),
        "inspection_tasks",
        "mode IN ('HISTORICAL_REPLAY', 'CURRENT_MONITORING')",
    )
    op.create_check_constraint(
        op.f("ck_inspection_tasks_area_value"),
        "inspection_tasks",
        "area_id IS NULL OR area_id IN ('batanghari', 'kubu-raya')",
    )
    op.create_index(
        "ix_inspection_tasks_assessment_id", "inspection_tasks", ["assessment_id"]
    )
    op.create_index("ix_inspection_tasks_hotspot_id", "inspection_tasks", ["hotspot_id"])
    op.create_index("ix_inspection_tasks_assignee_id", "inspection_tasks", ["assignee_id"])
    op.create_index(
        "ix_inspection_tasks_created_by_id", "inspection_tasks", ["created_by_id"]
    )
    op.create_index(
        "ix_inspection_tasks_mode_updated", "inspection_tasks", ["mode", "updated_at"]
    )

    op.create_check_constraint(
        op.f("ck_field_reports_result_value"),
        "field_reports",
        "result IN ('ACTIVE_FIRE_FOUND', 'BURN_SCAR_FOUND', 'NO_FIRE_FOUND', "
        "'LOCATION_INACCESSIBLE')",
    )
    op.create_index("ix_field_reports_task_id", "field_reports", ["task_id"])
    op.create_index(
        "ix_field_reports_submitted_by_id", "field_reports", ["submitted_by_id"]
    )

    op.add_column("task_status_history", sa.Column("actor_role", sa.String(30)))
    op.add_column("task_status_history", sa.Column("note", sa.Text()))
    op.execute(
        """
        UPDATE task_status_history AS history
        SET actor_role = actor.role
        FROM users AS actor
        WHERE history.actor_id = actor.id
        """
    )
    op.alter_column("task_status_history", "actor_role", nullable=False)
    op.create_check_constraint(
        op.f("ck_task_status_history_actor_role_value"),
        "task_status_history",
        "actor_role IN ('coordinator', 'field_officer')",
    )
    op.create_check_constraint(
        op.f("ck_task_status_history_from_status_value"),
        "task_status_history",
        "from_status IS NULL OR from_status IN ('OPEN', 'ASSIGNED', 'IN_PROGRESS', "
        "'SUBMITTED', 'VERIFIED', 'DISMISSED', 'NEEDS_FOLLOWUP')",
    )
    op.create_check_constraint(
        op.f("ck_task_status_history_to_status_value"),
        "task_status_history",
        "to_status IN ('OPEN', 'ASSIGNED', 'IN_PROGRESS', 'SUBMITTED', 'VERIFIED', "
        "'DISMISSED', 'NEEDS_FOLLOWUP')",
    )
    op.create_index(
        "ix_task_status_history_actor_id", "task_status_history", ["actor_id"]
    )

    for table in WORKFLOW_TABLES:
        op.execute(f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY")
    op.execute(
        """
        DO $$
        BEGIN
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
            REVOKE ALL ON TABLE public.users, public.inspection_tasks,
              public.field_reports, public.task_status_history FROM anon;
          END IF;
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
            REVOKE ALL ON TABLE public.users, public.inspection_tasks,
              public.field_reports, public.task_status_history FROM authenticated;
          END IF;
        END $$;
        """
    )


def downgrade() -> None:
    for table in WORKFLOW_TABLES:
        op.execute(f"ALTER TABLE public.{table} DISABLE ROW LEVEL SECURITY")

    op.drop_index("ix_task_status_history_actor_id", table_name="task_status_history")
    op.drop_constraint(
        op.f("ck_task_status_history_to_status_value"),
        "task_status_history",
        type_="check",
    )
    op.drop_constraint(
        op.f("ck_task_status_history_from_status_value"),
        "task_status_history",
        type_="check",
    )
    op.drop_constraint(
        op.f("ck_task_status_history_actor_role_value"),
        "task_status_history",
        type_="check",
    )
    op.drop_column("task_status_history", "note")
    op.drop_column("task_status_history", "actor_role")

    op.drop_index("ix_field_reports_submitted_by_id", table_name="field_reports")
    op.drop_index("ix_field_reports_task_id", table_name="field_reports")
    op.drop_constraint(
        op.f("ck_field_reports_result_value"), "field_reports", type_="check"
    )

    op.drop_index("ix_inspection_tasks_mode_updated", table_name="inspection_tasks")
    op.drop_index("ix_inspection_tasks_created_by_id", table_name="inspection_tasks")
    op.drop_index("ix_inspection_tasks_assignee_id", table_name="inspection_tasks")
    op.drop_index("ix_inspection_tasks_hotspot_id", table_name="inspection_tasks")
    op.drop_index("ix_inspection_tasks_assessment_id", table_name="inspection_tasks")
    op.drop_constraint(
        op.f("ck_inspection_tasks_area_value"), "inspection_tasks", type_="check"
    )
    op.drop_constraint(
        op.f("ck_inspection_tasks_mode_value"), "inspection_tasks", type_="check"
    )
    op.drop_column("inspection_tasks", "is_simulation")
    op.drop_column("inspection_tasks", "note")
    op.drop_column("inspection_tasks", "area_id")
    op.drop_column("inspection_tasks", "mode")
