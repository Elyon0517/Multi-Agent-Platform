"""Mark existing runs unlimited while retaining historical spending settings."""

from alembic import op

from agentlab.db.migration_scope import is_project_scope

revision = "remove_budget_limits"
down_revision = "run_unlimited_budget"


def upgrade() -> None:
    op.execute("ALTER TABLE run ALTER COLUMN budget_unlimited SET DEFAULT true")
    # The base run table is a read-only archive after project isolation.
    if is_project_scope():
        op.execute("UPDATE run SET budget_unlimited = true WHERE NOT budget_unlimited")


def downgrade() -> None:
    raise RuntimeError("Data-preserving migration")
