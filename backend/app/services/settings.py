"""Stored settings. Environment variables win over stored values."""
import os
from pathlib import Path

from ..config import DEFAULT_SOURCES, get_config
from ..models import Setting


def get(session, key, default=None):
    row = session.get(Setting, key)
    return default if row is None else row.value


def put(session, key, value):
    row = session.get(Setting, key)
    if row is None:
        session.add(Setting(key=key, value=value))
    else:
        row.value = value
    session.flush()


def sources(session):
    """Download folders: DJ_SOURCES if set, else the stored list, else the defaults."""
    if os.environ.get("DJ_SOURCES"):
        return list(get_config().sources)
    stored = get(session, "sources")
    if stored:
        return [Path(p).expanduser() for p in stored]
    return [Path(p).expanduser() for p in DEFAULT_SOURCES.split(":")]


def sources_locked():
    return bool(os.environ.get("DJ_SOURCES"))
