"""
Bring the database schema up to date. Run before starting the app:

    python -m app.db_migrate

- Empty database (a fresh deploy): create every table from the models and
  mark it as being at the latest migration. The migration chain can't build
  a database from nothing (its first revision only adds columns to tables
  that used to be created by the app at startup), and the models are the
  same schema the chain produces — `alembic check` confirms that on a
  migrated database.
- Database already under Alembic: apply any new migrations.
- Tables but no Alembic history: stop. Guessing which migrations it has
  would risk marking missing columns as present; stamp it by hand after
  checking (`alembic stamp <revision>`).
"""
from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import settings
from app.core.database import Base
import app.models  # noqa: F401  (registers every model on Base.metadata)

log = logging.getLogger("db_migrate")
ALEMBIC_INI = Path(__file__).resolve().parent.parent / "alembic.ini"


def _alembic_config() -> Config:
    cfg = Config(str(ALEMBIC_INI))
    cfg.set_main_option("script_location", str(ALEMBIC_INI.parent / "alembic"))
    return cfg


async def _inspect_and_bootstrap() -> str:
    """Returns "empty" (and creates the schema), "managed" or "unmanaged"."""
    engine = create_async_engine(settings.async_database_url)
    try:
        async with engine.begin() as conn:
            tables = set(await conn.run_sync(lambda c: inspect(c).get_table_names()))
            if "alembic_version" in tables:
                return "managed"
            if tables:
                return "unmanaged"
            await conn.run_sync(Base.metadata.create_all)
            return "empty"
    finally:
        await engine.dispose()


def migrate() -> int:
    state = asyncio.run(_inspect_and_bootstrap())
    cfg = _alembic_config()
    if state == "empty":
        command.stamp(cfg, "head")
        log.info("Fresh database: created the schema and stamped it at the latest migration.")
    elif state == "managed":
        command.upgrade(cfg, "head")
        log.info("Database is at the latest migration.")
    else:
        log.error(
            "The database has tables but no Alembic history, so it's unclear which migrations it has. "
            "Check its schema, then run `alembic stamp <revision>` and try again."
        )
        return 1
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s [%(name)s] %(message)s")
    sys.exit(migrate())
