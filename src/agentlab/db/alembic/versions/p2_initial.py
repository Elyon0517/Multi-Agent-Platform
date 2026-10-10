from pathlib import Path

from alembic import op

from agentlab.db.migration_scope import is_project_scope

revision = "p2_initial"
down_revision = None


def upgrade() -> None:
    root = Path(__file__).parents[2] / "migrations"
    for filename in ("0001_init.sql", "0002_model_alignment.sql"):
        sql = (root / filename).read_text().replace("BEGIN;", "").replace("COMMIT;", "")
        if is_project_scope():
            sql = sql.replace("CREATE EXTENSION IF NOT EXISTS vector;", "")
        op.get_bind().exec_driver_sql(sql)


def downgrade() -> None:
    raise RuntimeError("Data-preserving migration; automatic destructive downgrade is disabled")
