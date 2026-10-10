"""Allow independently budgeted summarizer calls in the global ledger."""

from alembic import op

from agentlab.db.migration_scope import base_table, is_project_scope

revision = "p6_summarizer"
down_revision = "usage_monitor"


def upgrade() -> None:
    if is_project_scope():
        return
    ledger = base_table("usage_ledger")
    op.execute(f"ALTER TABLE {ledger} DROP CONSTRAINT usage_ledger_source_check")
    op.execute(f"""ALTER TABLE {ledger} ADD CONSTRAINT usage_ledger_source_check
        CHECK(source IN ('run','turn','planning','summarization'))""")


def downgrade() -> None:
    raise RuntimeError("Data-preserving migration")
