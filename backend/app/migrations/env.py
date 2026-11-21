"""Alembic environment. Run through app.db.migrate() or `make migration`."""
from alembic import context
from sqlalchemy import create_engine

from app.models import Base

config = context.config
target_metadata = Base.metadata


def run():
    connectable = config.attributes.get("connection_engine") or create_engine(config.get_main_option("sqlalchemy.url"))
    with connectable.connect() as connection:
        # SQLite rebuilds a table to drop a column (batch mode). With foreign keys on, dropping the old table
        # would run the ON DELETE actions of every table that points to it (deleting or clearing their rows),
        # so they are off while migrating and checked afterwards.
        connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
        context.configure(connection=connection, target_metadata=target_metadata, render_as_batch=True)
        with context.begin_transaction():
            context.run_migrations()
        connection.commit()   # the PRAGMA above already opened a transaction, so the migration's own does not commit
        broken = connection.exec_driver_sql("PRAGMA foreign_key_check").fetchall()
        if broken:
            raise RuntimeError(f"Migration left rows pointing at missing rows: {broken[:5]}")


run()
