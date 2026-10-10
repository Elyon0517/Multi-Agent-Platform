"""Shared revision helpers and a guard against project migrations changing base tables."""

from __future__ import annotations

from typing import Any

from alembic import op
from sqlalchemy import text
from sqlalchemy.engine import Connection


def is_project_scope() -> bool:
    config = op.get_context().config
    assert config is not None
    return bool(config.attributes.get("migration_scope", "base") == "project")


def base_table(name: str) -> str:
    """Qualified SQL identifier for base-only operations (also check the scope)."""
    if is_project_scope():
        raise RuntimeError("base-only operations must be skipped in project scope")
    context = op.get_context()
    assert context.config is not None
    base = context.config.attributes["base_schema"]
    quote = op.get_bind().dialect.identifier_preparer.quote
    return f"{quote(base)}.{quote(name)}"


def base_structure(connection: Connection, schema: str) -> list[Any]:
    # Definitions, not OIDs, capture table/column/index/constraint/trigger changes.
    original = connection.exec_driver_sql("SHOW search_path").scalar_one()
    quote = connection.dialect.identifier_preparer.quote
    connection.exec_driver_sql(f"SET LOCAL search_path TO {quote(schema)}, public")
    result = list(
        connection.execute(
            text("""
        SELECT c.relname, c.relkind, a.attnum, a.attname,
               format_type(a.atttypid,a.atttypmod), a.attnotnull, a.attidentity, a.attgenerated,
               pg_get_expr(d.adbin,d.adrelid),
               (SELECT array_agg(pg_get_constraintdef(k.oid) ORDER BY k.conname)
                FROM pg_constraint k WHERE k.conrelid=c.oid),
               (SELECT array_agg(pg_get_indexdef(i.indexrelid) ORDER BY i.indexrelid::regclass::text)
                FROM pg_index i WHERE i.indrelid=c.oid),
               (SELECT array_agg(pg_get_triggerdef(t.oid) ORDER BY t.tgname)
                FROM pg_trigger t WHERE t.tgrelid=c.oid AND NOT t.tgisinternal)
        FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
        LEFT JOIN pg_attribute a ON a.attrelid=c.oid AND a.attnum>0 AND NOT a.attisdropped
        LEFT JOIN pg_attrdef d ON d.adrelid=c.oid AND d.adnum=a.attnum
        WHERE n.nspname=:schema AND c.relkind IN ('r','p') ORDER BY c.relname,a.attnum
    """),
            {"schema": schema},
        )
    )

    connection.execute(text("SELECT set_config('search_path', :original, true)"), {"original": original})
    return result
