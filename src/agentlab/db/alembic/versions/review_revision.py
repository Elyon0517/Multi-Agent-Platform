"""Bind persisted review artifacts and iterations to their source revision."""

from alembic import op

revision = "review_revision"
down_revision = "remove_budget_limits"


def upgrade() -> None:
    op.execute("ALTER TABLE artifact ADD COLUMN IF NOT EXISTS revision_id text")
    op.execute("ALTER TABLE iteration ADD COLUMN IF NOT EXISTS revision_id text")


def downgrade() -> None:
    raise RuntimeError("Data-preserving migration")
