"""Persist an explicitly authorized unlimited budget per run."""

from alembic import op

revision = "run_unlimited_budget"
down_revision = "p6_summarizer"


def upgrade() -> None:
    op.execute("ALTER TABLE run ADD COLUMN budget_unlimited boolean NOT NULL DEFAULT false")


def downgrade() -> None:
    raise RuntimeError("Data-preserving migration")
