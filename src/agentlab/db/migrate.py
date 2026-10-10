from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text


def upgrade(database_url: str, *, script_location: Path | None = None) -> None:
    url = database_url.replace("postgresql://", "postgresql+psycopg://", 1)
    engine = create_engine(url)
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT pg_advisory_lock(712460801)"))
            connection.commit()
            try:
                # All registered schemas advance atomically. A failed project migration also
                # rolls back the base schema and every version marker.
                with connection.begin():
                    base = connection.execute(text("SELECT current_schema()")).scalar_one()
                    quote = connection.dialect.identifier_preparer.quote
                    config = Config()
                    config.set_main_option("script_location", str(script_location or Path(__file__).parent / "alembic"))
                    config.attributes["connection"] = connection
                    registry = connection.execute(
                        text("SELECT to_regclass(:name)"), {"name": f"{base}.project_schema"}
                    ).scalar_one()
                    projects = (
                        list(
                            connection.execute(
                                text(f"SELECT schema_name FROM {quote(base)}.project_schema ORDER BY project_id")
                            ).scalars()
                        )
                        if registry
                        else []
                    )
                    version = connection.execute(
                        text("SELECT to_regclass(:name)"), {"name": f"{base}.alembic_version"}
                    ).scalar_one()
                    previous = (
                        connection.execute(text(f"SELECT version_num FROM {quote(base)}.alembic_version")).scalar_one()
                        if version
                        else None
                    )
                    for schema in projects:
                        connection.execute(text(f"SET LOCAL search_path TO {quote(schema)}, {quote(base)}, public"))
                        if connection.execute(text("SELECT current_schema()")).scalar_one() != schema:
                            raise RuntimeError(f"registered project schema is missing: {schema}")
                        tracked = connection.execute(
                            text("SELECT to_regclass(:name)"), {"name": f"{schema}.alembic_version"}
                        ).scalar_one()
                        if not tracked:
                            if previous is None:
                                raise RuntimeError("cannot adopt project schema without base migration version")
                            command.stamp(config, previous)
                    for schema in [base, *projects]:
                        connection.execute(text(f"SET LOCAL search_path TO {quote(schema)}, {quote(base)}, public"))
                        config.attributes["migration_scope"] = "base" if schema == base else "project"
                        config.attributes["base_schema"] = base
                        command.upgrade(config, "head")
                    connection.execute(text(f"SET LOCAL search_path TO {quote(base)}, public"))
                    config.attributes["migration_scope"] = "base"
                    from agentlab.db.usage_backfill import backfill_usage

                    backfill_usage(connection, base)
            finally:
                connection.execute(text("SELECT pg_advisory_unlock(712460801)"))
                connection.commit()
    finally:
        engine.dispose()

    from agentlab.db.isolation import migrate

    migrate(database_url)
