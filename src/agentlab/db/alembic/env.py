from alembic import context

from agentlab.db.migration_scope import base_structure

connection = context.config.attributes["connection"]
schema = connection.exec_driver_sql("SELECT current_schema()").scalar_one()
project_scope = context.config.attributes.get("migration_scope") == "project"
base = str(context.config.attributes.get("base_schema", ""))
if project_scope and (not base or schema == base):
    raise RuntimeError("project migration requires a separate target schema and base_schema")
context.configure(connection=connection, version_table_schema=schema)
with context.begin_transaction():
    before = base_structure(connection, base) if project_scope else None
    context.run_migrations()
    if project_scope and base_structure(connection, base) != before:
        raise RuntimeError("project migration changed base schema structure")
