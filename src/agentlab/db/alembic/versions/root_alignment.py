from alembic import op

revision = "root_alignment"
down_revision = "root_session"


def upgrade() -> None:
    # Some legacy project schemas were adopted with a head marker despite missing
    # this column. Repair only the current schema; project guard remains effective.
    op.execute("ALTER TABLE run ADD COLUMN IF NOT EXISTS thread_id text")


def downgrade() -> None:
    raise RuntimeError("Data-preserving migration")
