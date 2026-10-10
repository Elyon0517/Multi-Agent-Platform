from alembic import context

connection = context.config.attributes["connection"]
schema = connection.exec_driver_sql("SELECT current_schema()").scalar_one()
context.configure(connection=connection, version_table_schema=schema)
with context.begin_transaction():
    context.run_migrations()
