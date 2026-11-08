"""SQLite engine and sessions. One database file, shared by the server and the CLI."""
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from .config import get_config

_engine = None
_Session = None


def engine():
    global _engine, _Session
    if _engine is None:
        path = Path(get_config().db_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        _engine = create_engine(f"sqlite:///{path}", connect_args={"check_same_thread": False, "timeout": 30})

        @event.listens_for(_engine, "connect")
        def _pragmas(connection, _):
            cursor = connection.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA busy_timeout=30000")
            cursor.close()

        _Session = sessionmaker(bind=_engine, expire_on_commit=False)
    return _engine


def reset_engine():
    """Forget the engine (tests switch databases)."""
    global _engine, _Session
    if _engine is not None:
        _engine.dispose()
    _engine = _Session = None


@contextmanager
def session_scope():
    engine()
    session = _Session()
    try:
        yield session
        session.commit()
    except BaseException:
        session.rollback()
        raise
    finally:
        session.close()


def migrate():
    """Bring the database schema up to date (Alembic)."""
    from alembic import command
    from alembic.config import Config as AlembicConfig

    here = Path(__file__).resolve().parent
    cfg = AlembicConfig()
    cfg.set_main_option("script_location", str(here / "migrations"))
    cfg.set_main_option("sqlalchemy.url", str(engine().url))
    cfg.attributes["connection_engine"] = engine()
    command.upgrade(cfg, "head")
