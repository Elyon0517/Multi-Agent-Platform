"""Global usage ledger. Backfill runs after all project migrations finish."""

from alembic import op

from agentlab.db.migration_scope import base_table, is_project_scope

revision = "usage_monitor"
down_revision = "root_alignment"


def upgrade() -> None:
    if is_project_scope():
        return
    ledger = base_table("usage_ledger")
    op.execute(f"""CREATE TABLE {ledger} (
        id text PRIMARY KEY, ts timestamptz NOT NULL DEFAULT now(), role text NOT NULL,
        model_alias text NOT NULL, model text NOT NULL,
        tokens_in bigint NOT NULL CHECK(tokens_in >= 0),
        tokens_out bigint NOT NULL CHECK(tokens_out >= 0),
        cost_cents numeric NOT NULL CHECK(cost_cents >= 0),
        source text NOT NULL CHECK(source IN ('run','turn','planning')),
        ref_id text NOT NULL, project_id text, metered boolean NOT NULL,
        calls integer NOT NULL DEFAULT 1 CHECK(calls >= 0))""")
    op.execute(f"CREATE INDEX usage_ledger_role_idx ON {ledger} (role)")


def downgrade() -> None:
    raise RuntimeError("Data-preserving migration")
