from alembic import op

revision = "p2_recovery"
down_revision = "p2_initial"


def upgrade() -> None:
    op.get_bind().exec_driver_sql("""
        ALTER TABLE project ADD COLUMN IF NOT EXISTS payload jsonb;
        ALTER TABLE memory ADD COLUMN IF NOT EXISTS payload jsonb;
        CREATE TABLE run_checkpoint (
            run_id text PRIMARY KEY REFERENCES run(id),
            data jsonb NOT NULL,
            updated_at timestamptz NOT NULL DEFAULT now()
        );
        CREATE TABLE state_record (
            kind text NOT NULL,
            key text NOT NULL,
            data jsonb NOT NULL,
            updated_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (kind, key)
        );
        ALTER TABLE step ADD COLUMN IF NOT EXISTS ordinal bigserial;
        ALTER TABLE artifact ADD COLUMN IF NOT EXISTS ordinal bigserial;
        ALTER TABLE approval ADD COLUMN IF NOT EXISTS ordinal bigserial;
    """)


def downgrade() -> None:
    raise RuntimeError("Data-preserving migration; automatic destructive downgrade is disabled")
