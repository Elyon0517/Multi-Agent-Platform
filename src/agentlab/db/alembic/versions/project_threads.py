from alembic import op

revision = "project_threads"
down_revision = "p2_recovery"


def upgrade() -> None:
    op.execute("ALTER TABLE run ADD COLUMN IF NOT EXISTS thread_id text")


def downgrade() -> None:
    raise RuntimeError("Data-preserving migration")
