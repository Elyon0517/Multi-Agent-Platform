from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text


def upgrade(database_url: str) -> None:
    url = database_url.replace("postgresql://", "postgresql+psycopg://", 1)
    engine = create_engine(url)
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT pg_advisory_lock(712460801)"))
            connection.commit()
            try:
                config = Config()
                config.set_main_option("script_location", str(Path(__file__).parent / "alembic"))
                config.attributes["connection"] = connection
                command.upgrade(config, "head")
            finally:
                connection.execute(text("SELECT pg_advisory_unlock(712460801)"))
                connection.commit()
    finally:
        engine.dispose()
